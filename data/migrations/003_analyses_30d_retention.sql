-- ============================================================================
-- PHASE 5 MIGRATION: 30-Day Storage Retention Cleanup (Analyses, Resumes, Jobs)
-- ============================================================================
-- Automatically purges records older than 30 days to keep Supabase database
-- storage within limits. Can be invoked manually via `SELECT public.cleanup_expired_storage();`
-- or scheduled automatically via `pg_cron` (if enabled on the Supabase project).
-- ============================================================================

create or replace function public.cleanup_expired_storage(retention_days integer default 30)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  cutoff timestamptz := now() - make_interval(days => retention_days);
  del_analyses integer := 0;
  del_resumes integer := 0;
  del_jobs integer := 0;
  del_resume_evidence integer := 0;
  del_jd_requirements integer := 0;
  del_guest_ip integer := 0;
begin
  -- 1. Delete expired analyses
  with deleted as (
    delete from public.analyses
    where created_at < cutoff
    returning 1
  )
  select count(*) into del_analyses from deleted;

  -- 2. Delete expired resume evidence vectors
  with deleted as (
    delete from public.resume_evidence
    where created_at < cutoff
    returning 1
  )
  select count(*) into del_resume_evidence from deleted;

  -- 3. Delete expired JD requirement vectors
  with deleted as (
    delete from public.jd_requirements
    where created_at < cutoff
    returning 1
  )
  select count(*) into del_jd_requirements from deleted;

  -- 4. Delete expired saved resumes (not referenced by any remaining active analysis)
  with deleted as (
    delete from public.resumes r
    where r.created_at < cutoff
      and not exists (
        select 1 from public.analyses a where a.resume_id = r.id
      )
    returning 1
  )
  select count(*) into del_resumes from deleted;

  -- 5. Delete expired jobs (not referenced by any remaining active analysis)
  with deleted as (
    delete from public.jobs j
    where j.created_at < cutoff
      and not exists (
        select 1 from public.analyses a where a.job_id = j.id
      )
    returning 1
  )
  select count(*) into del_jobs from deleted;

  -- 6. Delete expired guest IP rate-limit rows
  with deleted as (
    delete from public.guest_ip_usage
    where last_analysis_at < cutoff
    returning 1
  )
  select count(*) into del_guest_ip from deleted;

  return jsonb_build_object(
    'analyses_deleted', del_analyses,
    'resumes_deleted', del_resumes,
    'jobs_deleted', del_jobs,
    'resume_evidence_deleted', del_resume_evidence,
    'jd_requirements_deleted', del_jd_requirements,
    'guest_ip_deleted', del_guest_ip,
    'cutoff', cutoff
  );
end;
$$;

-- Optional: If pg_cron is enabled on your Supabase instance, schedule daily cleanup at 03:00 UTC.
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.schedule(
      'proofit-30d-storage-cleanup',
      '0 3 * * *',
      $cron$select public.cleanup_expired_storage(30);$cron$
    );
  end if;
exception
  when others then
    -- Ignore if pg_cron is not available or permissions disallow cron scheduling
    null;
end;
$$;

