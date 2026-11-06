-- Review and apply after 007, before deploying checkout status polling changes.
begin;

-- One bounded sliding-window bucket per account, not one row per poll.
create table public.checkout_status_requests (
  user_id uuid primary key references auth.users(id) on delete cascade,
  hits timestamptz[] not null check (cardinality(hits) <= 10000),
  expires_at timestamptz not null
);
create index checkout_status_requests_expiry on public.checkout_status_requests(expires_at);
alter table public.checkout_status_requests enable row level security;
revoke all on table public.checkout_status_requests from public, anon, authenticated;
grant all on table public.checkout_status_requests to service_role;

-- Cache/lease storage is constant per existing checkout. No new rows per refresh.
alter table public.checkout_sessions
  add column status_refresh_after timestamptz,
  add column status_refresh_until timestamptz,
  add column status_refresh_token uuid,
  add column status_refresh_error boolean not null default false;

create function public.admit_checkout_status(p_user_id uuid, p_limit integer)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_now timestamptz;
  v_hits timestamptz[];
begin
  if p_user_id is null or p_limit is null or p_limit < 0 or p_limit > 10000 then
    raise exception 'Invalid checkout status admission';
  end if;
  if p_limit = 0 then
    return jsonb_build_object('allowed', false);
  end if;
  perform pg_advisory_xact_lock(hashtext('checkout_status:' || p_user_id::text));
  v_now := clock_timestamp();
  -- Bounded opportunistic cleanup. Skip locked rows to avoid cross-account deadlocks.
  delete from public.checkout_status_requests where user_id in (
    select user_id from public.checkout_status_requests
    where expires_at <= v_now order by expires_at limit 1000 for update skip locked
  );
  select array(select h from unnest(hits) as h where h > v_now - interval '1 minute')
    into v_hits from public.checkout_status_requests where user_id = p_user_id for update;
  v_hits := coalesce(v_hits, array[]::timestamptz[]);
  if cardinality(v_hits) >= p_limit then
    return jsonb_build_object('allowed', false);
  end if;
  insert into public.checkout_status_requests(user_id, hits, expires_at)
    values (p_user_id, array_append(v_hits, v_now), v_now + interval '1 minute')
    on conflict (user_id) do update set hits = excluded.hits, expires_at = excluded.expires_at;
  return jsonb_build_object('allowed', true);
end;
$$;

create function public.claim_checkout_status_refresh(
  p_session_id uuid, p_user_id uuid, p_token uuid, p_lease_seconds integer
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_session public.checkout_sessions%rowtype;
  v_now timestamptz;
  v_refresh boolean := false;
begin
  if p_token is null or p_lease_seconds is null or p_lease_seconds < 1 or p_lease_seconds > 120 then
    raise exception 'Invalid checkout status lease';
  end if;
  select * into v_session from public.checkout_sessions
    where id = p_session_id and user_id = p_user_id for update;
  if not found then
    raise exception 'Unknown checkout';
  end if;
  v_now := clock_timestamp();
  if v_session.status = 'pending' then
    if v_session.provider = 'stripe_sandbox' and v_session.provider_ref is not null
        and coalesce(v_session.status_refresh_after, '-infinity'::timestamptz) <= v_now
        and coalesce(v_session.status_refresh_until, '-infinity'::timestamptz) <= v_now then
      update public.checkout_sessions set status_refresh_token = p_token,
        status_refresh_until = v_now + p_lease_seconds * interval '1 second',
        status_refresh_error = false
        where id = p_session_id returning * into v_session;
      v_refresh := true;
    elsif v_session.expires_at <= v_now
        and coalesce(v_session.status_refresh_until, '-infinity'::timestamptz) <= v_now then
      update public.checkout_sessions set status = 'expired', status_refresh_error = false
        where id = p_session_id returning * into v_session;
    end if;
  end if;
  return jsonb_build_object('refresh', v_refresh, 'provider_error',
    v_session.status = 'pending' and v_session.status_refresh_error, 'session', to_jsonb(v_session));
end;
$$;

create function public.finish_checkout_status_refresh(
  p_session_id uuid, p_user_id uuid, p_token uuid, p_status text, p_cache_seconds integer
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_session public.checkout_sessions%rowtype;
  v_now timestamptz;
begin
  if p_token is null or p_status is null or p_status not in ('pending', 'paid', 'expired', 'error')
      or p_cache_seconds is null or p_cache_seconds < 1 or p_cache_seconds > 300 then
    raise exception 'Invalid checkout status result';
  end if;
  select * into v_session from public.checkout_sessions
    where id = p_session_id and user_id = p_user_id for update;
  if not found then
    raise exception 'Unknown checkout';
  end if;
  v_now := clock_timestamp();
  -- Fence abandoned workers, and never overwrite a webhook's terminal status.
  if v_session.status_refresh_token = p_token then
    update public.checkout_sessions set
      status = case when status <> 'pending' then status
        when p_status = 'paid' then 'paid'
        when p_status = 'expired' or expires_at <= v_now then 'expired' else 'pending' end,
      paid_at = case when status = 'pending' and p_status = 'paid'
        then coalesce(paid_at, v_now) else paid_at end,
      status_refresh_after = v_now + p_cache_seconds * interval '1 second',
      status_refresh_until = null, status_refresh_token = null,
      status_refresh_error = (status = 'pending' and p_status = 'error' and expires_at > v_now)
      where id = p_session_id returning * into v_session;
  end if;
  return jsonb_build_object('refresh', false, 'provider_error',
    v_session.status = 'pending' and v_session.status_refresh_error, 'session', to_jsonb(v_session));
end;
$$;

revoke all on function public.admit_checkout_status(uuid, integer) from public, anon, authenticated;
revoke all on function public.claim_checkout_status_refresh(uuid, uuid, uuid, integer) from public, anon, authenticated;
revoke all on function public.finish_checkout_status_refresh(uuid, uuid, uuid, text, integer) from public, anon, authenticated;
grant execute on function public.admit_checkout_status(uuid, integer) to service_role;
grant execute on function public.claim_checkout_status_refresh(uuid, uuid, uuid, integer) to service_role;
grant execute on function public.finish_checkout_status_refresh(uuid, uuid, uuid, text, integer) to service_role;

commit;
