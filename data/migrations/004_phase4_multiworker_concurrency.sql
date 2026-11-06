-- ============================================================================
-- PHASE 4 MIGRATION: Multi-Worker Concurrency, Atomic Quotas & Retry Locking
-- ============================================================================
-- NOTE: Prepare for review only. Do NOT apply to production automatically.
-- Coordinates retries, user quota reservations, guest IP rate limits, and
-- abandoned work recovery across multiple server processes / worker instances.
-- ============================================================================

-- ============================================================================
-- 1. Ensure required tables exist with proper schema and indexes
-- ============================================================================

-- Guest IP usage tracking (salted SHA-256 hash only)
create table if not exists public.guest_ip_usage (
  ip_hash text primary key,
  last_analysis_at timestamptz not null default now()
);

-- Usage reservations table for concurrency-safe quota reservations
create table if not exists public.usage_reservations (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('analysis', 'rewrite')),
  status text not null default 'active' check (status in ('active', 'committed', 'released')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 minutes')
);

-- Usage events table
create table if not exists public.usage_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('analysis', 'rewrite')),
  created_at timestamptz not null default now()
);

-- Schema additions for idempotency and abandoned work tracking
alter table public.analyses
  add column if not exists retried_by text references public.analyses(id) on delete set null,
  add column if not exists reservation_id text,
  add column if not exists updated_at timestamptz not null default now();

alter table public.usage_events
  add column if not exists reservation_id text;

-- Unique constraint ensures a reservation can never produce more than one usage_event
create unique index if not exists idx_usage_events_reservation_id
  on public.usage_events(reservation_id)
  where reservation_id is not null;

create index if not exists idx_usage_reservations_expires
  on public.usage_reservations(expires_at)
  where status = 'active';

-- 2. Atomic User Quota Check & Reservation
create or replace function public.reserve_user_quota(
  p_user_id uuid,
  p_kind text,
  p_reservation_id text,
  p_limit integer,
  p_window_start timestamptz,
  p_expires_at timestamptz default (now() + interval '10 minutes')
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_used integer := 0;
  v_reserved integer := 0;
  v_total integer := 0;
  v_existing record;
  v_now timestamptz := now();
begin
  if p_kind not in ('analysis', 'rewrite') then
    raise exception 'Invalid quota kind: %', p_kind;
  end if;

  -- Serialize all quota checks and reservations for this user_id across workers
  perform pg_advisory_xact_lock(hashtext('quota:' || p_user_id::text || ':' || p_kind));

  -- Idempotency check if the same reservation_id is retried
  select id, status, expires_at into v_existing
  from public.usage_reservations
  where id = p_reservation_id;

  if found then
    if v_existing.status = 'active' and v_existing.expires_at > v_now then
      return jsonb_build_object(
        'allowed', true,
        'reservation_id', p_reservation_id,
        'idempotent', true
      );
    end if;
  end if;

  -- Expire stale active reservations for this user so abandoned work does not permanently block quota
  update public.usage_reservations
  set status = 'released'
  where user_id = p_user_id
    and kind = p_kind
    and status = 'active'
    and expires_at <= v_now;

  -- Unlimited plan (p_limit is null)
  if p_limit is null then
    insert into public.usage_reservations (id, user_id, kind, status, created_at, expires_at)
    values (p_reservation_id, p_user_id, p_kind, 'active', v_now, p_expires_at)
    on conflict (id) do update
      set status = 'active',
          expires_at = excluded.expires_at;

    return jsonb_build_object(
      'allowed', true,
      'reservation_id', p_reservation_id,
      'used', 0,
      'limit', null
    );
  end if;

  -- Count committed usage events within current billing/rolling window
  select count(*) into v_used
  from public.usage_events
  where user_id = p_user_id
    and kind = p_kind
    and created_at >= p_window_start;

  -- Count in-flight non-expired reservations within window
  select count(*) into v_reserved
  from public.usage_reservations
  where user_id = p_user_id
    and kind = p_kind
    and status = 'active'
    and expires_at > v_now
    and created_at >= p_window_start;

  v_total := v_used + v_reserved;

  if v_total >= p_limit then
    return jsonb_build_object(
      'allowed', false,
      'code', 'quota_exceeded',
      'used', v_total,
      'limit', p_limit
    );
  end if;

  insert into public.usage_reservations (id, user_id, kind, status, created_at, expires_at)
  values (p_reservation_id, p_user_id, p_kind, 'active', v_now, p_expires_at);

  return jsonb_build_object(
    'allowed', true,
    'reservation_id', p_reservation_id,
    'used', v_total + 1,
    'limit', p_limit
  );
end;
$$;

-- 3. Idempotent Reservation Commit
create or replace function public.commit_usage_reservation(
  p_reservation_id text,
  p_user_id uuid default null,
  p_kind text default 'analysis'
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_res record;
  v_now timestamptz := now();
begin
  if p_reservation_id is not null then
    select id, user_id, kind, status into v_res
    from public.usage_reservations
    where id = p_reservation_id
    for update;

    if not found then
      if p_user_id is not null then
        insert into public.usage_events (user_id, kind, reservation_id, created_at)
        values (p_user_id, p_kind, p_reservation_id, v_now)
        on conflict (reservation_id) where reservation_id is not null do nothing;
      end if;
      return jsonb_build_object('committed', true, 'status', 'untracked_committed');
    end if;

    if v_res.status = 'committed' then
      return jsonb_build_object('committed', true, 'status', 'already_committed');
    end if;

    if v_res.status = 'released' then
      return jsonb_build_object('committed', false, 'status', 'already_released');
    end if;

    update public.usage_reservations
    set status = 'committed'
    where id = p_reservation_id;

    insert into public.usage_events (user_id, kind, reservation_id, created_at)
    values (v_res.user_id, v_res.kind, p_reservation_id, v_now)
    on conflict (reservation_id) where reservation_id is not null do nothing;

    return jsonb_build_object('committed', true, 'status', 'committed');
  else
    if p_user_id is not null then
      insert into public.usage_events (user_id, kind, created_at)
      values (p_user_id, p_kind, v_now);
    end if;
    return jsonb_build_object('committed', true, 'status', 'direct_event');
  end if;
end;
$$;

-- 4. Idempotent Reservation Release
create or replace function public.release_usage_reservation(
  p_reservation_id text
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_res record;
begin
  if p_reservation_id is null then
    return jsonb_build_object('released', true, 'status', 'no_reservation');
  end if;

  select id, status into v_res
  from public.usage_reservations
  where id = p_reservation_id
  for update;

  if not found then
    return jsonb_build_object('released', true, 'status', 'not_found');
  end if;

  if v_res.status = 'committed' then
    return jsonb_build_object('released', false, 'status', 'already_committed');
  end if;

  if v_res.status = 'released' then
    return jsonb_build_object('released', true, 'status', 'already_released');
  end if;

  update public.usage_reservations
  set status = 'released'
  where id = p_reservation_id;

  return jsonb_build_object('released', true, 'status', 'released');
end;
$$;

-- 5. Atomic Retry Claim & Abandoned Work Recovery
create or replace function public.claim_analysis_retry(
  p_original_id text,
  p_child_id text,
  p_resume_id text,
  p_job_id text,
  p_country text,
  p_user_id uuid default null,
  p_reservation_id text default null,
  p_abandoned_seconds integer default 600
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_orig record;
  v_child record;
  v_now timestamptz := now();
  v_cutoff timestamptz := v_now - make_interval(secs => greatest(1, p_abandoned_seconds));
begin
  -- Lock the original analysis row to serialize concurrent retry attempts across workers
  select id, resume_id, job_id, country, status, user_id, retried_by, reservation_id, created_at
  into v_orig
  from public.analyses
  where id = p_original_id
  for update;

  if not found then
    return jsonb_build_object('success', false, 'code', 'ANALYSIS_NOT_FOUND');
  end if;

  -- If original itself is queued/running, check whether it has been abandoned
  if v_orig.status in ('queued', 'running') then
    if v_orig.created_at <= v_cutoff then
      update public.analyses
      set status = 'failed',
          error_message = 'Analysis timed out or was abandoned.',
          updated_at = v_now
      where id = v_orig.id;

      if v_orig.reservation_id is not null then
        update public.usage_reservations
        set status = 'released'
        where id = v_orig.reservation_id and status = 'active';
      end if;
    else
      return jsonb_build_object(
        'success', false,
        'code', 'ANALYSIS_IN_PROGRESS',
        'message', 'Cannot retry an analysis that is still queued or running.'
      );
    end if;
  end if;

  -- Check if an active retry child already exists
  if v_orig.retried_by is not null then
    select id, status, created_at, reservation_id
    into v_child
    from public.analyses
    where id = v_orig.retried_by
    for update;

    if found and v_child.status in ('queued', 'running') then
      if v_child.created_at > v_cutoff then
        return jsonb_build_object(
          'success', false,
          'code', 'ANALYSIS_IN_PROGRESS',
          'message', 'A retry for this analysis is already in progress.',
          'active_retry_id', v_child.id
        );
      else
        -- Recover abandoned child analysis and release its uncompleted reservation
        update public.analyses
        set status = 'failed',
            error_message = 'Analysis timed out or was abandoned.',
            updated_at = v_now
        where id = v_child.id;

        if v_child.reservation_id is not null then
          update public.usage_reservations
          set status = 'released'
          where id = v_child.reservation_id and status = 'active';
        end if;
      end if;
    end if;
  end if;

  -- Insert the new retry analysis and atomically link retried_by
  insert into public.analyses (
    id, resume_id, job_id, country, status, user_id, reservation_id, created_at, updated_at
  ) values (
    p_child_id,
    coalesce(p_resume_id, v_orig.resume_id),
    coalesce(p_job_id, v_orig.job_id),
    coalesce(p_country, v_orig.country),
    'queued',
    coalesce(p_user_id, v_orig.user_id),
    p_reservation_id,
    v_now,
    v_now
  );

  update public.analyses
  set retried_by = p_child_id,
      updated_at = v_now
  where id = p_original_id;

  return jsonb_build_object(
    'success', true,
    'analysis_id', p_child_id,
    'status', 'queued'
  );
end;
$$;

-- 6. Atomic Guest IP Usage Reservation & Release
create or replace function public.reserve_guest_usage(
  p_ip_hash text,
  p_ttl_hours numeric default 24.0
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_rec record;
  v_now timestamptz := now();
  v_cutoff timestamptz := v_now - (greatest(0.01, p_ttl_hours) || ' hours')::interval;
  v_prev timestamptz := null;
begin
  perform pg_advisory_xact_lock(hashtext('guest_ip:' || p_ip_hash));

  select ip_hash, last_analysis_at into v_rec
  from public.guest_ip_usage
  where ip_hash = p_ip_hash
  for update;

  if found then
    if v_rec.last_analysis_at > v_cutoff then
      return jsonb_build_object(
        'allowed', false,
        'last_analysis_at', v_rec.last_analysis_at
      );
    end if;
    v_prev := v_rec.last_analysis_at;
  end if;

  insert into public.guest_ip_usage (ip_hash, last_analysis_at)
  values (p_ip_hash, v_now)
  on conflict (ip_hash) do update
    set last_analysis_at = excluded.last_analysis_at;

  return jsonb_build_object(
    'allowed', true,
    'last_analysis_at', v_now,
    'prev_last_analysis_at', v_prev
  );
end;
$$;

create or replace function public.release_guest_usage(
  p_ip_hash text,
  p_prev_last_analysis_at timestamptz default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  perform pg_advisory_xact_lock(hashtext('guest_ip:' || p_ip_hash));

  if p_prev_last_analysis_at is not null then
    update public.guest_ip_usage
    set last_analysis_at = p_prev_last_analysis_at
    where ip_hash = p_ip_hash;
  else
    delete from public.guest_ip_usage
    where ip_hash = p_ip_hash;
  end if;

  return jsonb_build_object('released', true);
end;
$$;

-- 7. Permissions & Row-Level Security Lockdown
-- Ensure clients (anon / authenticated) cannot execute server-only RPCs or
-- mutate reservations, usage_events, or guest_ip_usage directly.
alter table public.usage_reservations enable row level security;
alter table public.usage_events enable row level security;
alter table public.guest_ip_usage enable row level security;

revoke all on table public.usage_reservations from public, anon, authenticated;
grant select on table public.usage_reservations to authenticated;
grant all on table public.usage_reservations to service_role;

revoke all on table public.usage_events from public, anon, authenticated;
grant select on table public.usage_events to authenticated;
grant all on table public.usage_events to service_role;

revoke all on table public.guest_ip_usage from public, anon, authenticated;
grant all on table public.guest_ip_usage to service_role;

revoke all on function public.reserve_user_quota(uuid, text, text, integer, timestamptz, timestamptz) from public, anon, authenticated;
grant execute on function public.reserve_user_quota(uuid, text, text, integer, timestamptz, timestamptz) to service_role;

revoke all on function public.commit_usage_reservation(text, uuid, text) from public, anon, authenticated;
grant execute on function public.commit_usage_reservation(text, uuid, text) to service_role;

revoke all on function public.release_usage_reservation(text) from public, anon, authenticated;
grant execute on function public.release_usage_reservation(text) to service_role;

revoke all on function public.claim_analysis_retry(text, text, text, text, text, uuid, text, integer) from public, anon, authenticated;
grant execute on function public.claim_analysis_retry(text, text, text, text, text, uuid, text, integer) to service_role;

revoke all on function public.reserve_guest_usage(text, numeric) from public, anon, authenticated;
grant execute on function public.reserve_guest_usage(text, numeric) to service_role;

revoke all on function public.release_guest_usage(text, timestamptz) from public, anon, authenticated;
grant execute on function public.release_guest_usage(text, timestamptz) to service_role;

