-- Apply before deploying the corresponding API. Admission attempts are not refunded.
begin;
create table if not exists public.analysis_attempts (
  id bigint generated always as identity primary key,
  subject text not null,
  created_at timestamptz not null default now()
);
create index if not exists analysis_attempts_subject_time
  on public.analysis_attempts(subject, created_at);
create index if not exists analysis_attempts_time on public.analysis_attempts(created_at);

alter table public.analysis_attempts enable row level security;
revoke all on table public.analysis_attempts from public, anon, authenticated;
grant all on table public.analysis_attempts to service_role;

create or replace function public.reserve_analysis_attempt(p_subject text, p_limit integer)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_count integer;
  v_now timestamptz;
begin
  if p_subject is null or length(p_subject) = 0 or p_limit is null or p_limit <= 0 then
    return jsonb_build_object('allowed', false);
  end if;
  perform pg_advisory_xact_lock(hashtext('analysis_attempt:' || p_subject));
  v_now := clock_timestamp();
  delete from public.analysis_attempts where created_at <= v_now - interval '1 hour';
  select count(*) into v_count from public.analysis_attempts
    where subject = p_subject and created_at > v_now - interval '1 hour';
  if v_count >= p_limit then
    return jsonb_build_object('allowed', false);
  end if;
  insert into public.analysis_attempts(subject, created_at) values (p_subject, v_now);
  return jsonb_build_object('allowed', true);
end;
$$;
revoke all on function public.reserve_analysis_attempt(text, integer) from public, anon, authenticated;
grant execute on function public.reserve_analysis_attempt(text, integer) to service_role;
commit;
