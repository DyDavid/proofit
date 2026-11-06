-- Apply before deploying the corresponding API. Pending uploads count toward quota.
begin;

create table if not exists public.resume_upload_slots (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  expires_at timestamptz not null
);
create index if not exists resume_upload_slots_user_expiry
  on public.resume_upload_slots(user_id, expires_at);

alter table public.resume_upload_slots enable row level security;
revoke all on table public.resume_upload_slots from public, anon, authenticated;
grant all on table public.resume_upload_slots to service_role;

create or replace function public.reserve_resume_slot(
  p_user_id uuid, p_slot_id text, p_limit integer, p_ttl_seconds numeric
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_now timestamptz;
  v_used bigint;
  v_pending bigint;
begin
  if p_user_id is null or p_slot_id is null or length(p_slot_id) = 0
      or p_limit is null or p_limit <= 0
      or p_ttl_seconds is null or p_ttl_seconds <= 0 then
    return jsonb_build_object('allowed', false);
  end if;
  perform pg_advisory_xact_lock(hashtext('resume_slot:' || p_user_id::text));
  v_now := clock_timestamp();
  delete from public.resume_upload_slots
    where user_id = p_user_id and expires_at <= v_now;
  select count(*) into v_used from public.resumes where user_id = p_user_id;
  select count(*) into v_pending from public.resume_upload_slots where user_id = p_user_id;
  if v_used + v_pending >= p_limit then
    return jsonb_build_object('allowed', false);
  end if;
  insert into public.resume_upload_slots(id, user_id, expires_at)
    values (p_slot_id, p_user_id, v_now + p_ttl_seconds * interval '1 second');
  return jsonb_build_object('allowed', true);
end;
$$;

create or replace function public.commit_resume_slot(
  p_user_id uuid, p_slot_id text, p_resume jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform pg_advisory_xact_lock(hashtext('resume_slot:' || p_user_id::text));
  -- Retrying after a lost response must not create another resume.
  if exists (select 1 from public.resumes where id = p_slot_id and user_id = p_user_id) then
    return jsonb_build_object('saved', true);
  end if;
  if not exists (
    select 1 from public.resume_upload_slots
      where id = p_slot_id and user_id = p_user_id and expires_at > clock_timestamp()
  ) then
    return jsonb_build_object('saved', false);
  end if;
  -- Save and consume in one transaction. Release uses the same lock, so a
  -- canceled request cannot release quota while a delayed save is committing.
  insert into public.resumes(id, user_id, filename, content_type, size_bytes, raw_text, normalized)
    values (
      p_slot_id, p_user_id, p_resume->>'filename', p_resume->>'content_type',
      (p_resume->>'size_bytes')::integer, p_resume->>'raw_text',
      nullif(p_resume->'normalized', 'null'::jsonb)
    );
  delete from public.resume_upload_slots where id = p_slot_id and user_id = p_user_id;
  return jsonb_build_object('saved', true);
end;
$$;

create or replace function public.release_resume_slot(p_user_id uuid, p_slot_id text)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform pg_advisory_xact_lock(hashtext('resume_slot:' || p_user_id::text));
  delete from public.resume_upload_slots where id = p_slot_id and user_id = p_user_id;
  return jsonb_build_object('released', true);
end;
$$;

revoke all on function public.reserve_resume_slot(uuid, text, integer, numeric) from public, anon, authenticated;
revoke all on function public.commit_resume_slot(uuid, text, jsonb) from public, anon, authenticated;
revoke all on function public.release_resume_slot(uuid, text) from public, anon, authenticated;
grant execute on function public.reserve_resume_slot(uuid, text, integer, numeric) to service_role;
grant execute on function public.commit_resume_slot(uuid, text, jsonb) to service_role;
grant execute on function public.release_resume_slot(uuid, text) to service_role;

commit;
