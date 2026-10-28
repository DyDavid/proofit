-- ============================================================================
-- PHASE 1 MIGRATION: Supabase Auth, Profiles, User Ownership & RLS
-- ============================================================================
-- Run this migration in the Supabase SQL Editor after reviewing.
-- ============================================================================

-- 1. Profiles table: one row per authenticated user
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
  for select using (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id)
  values (new.id)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 2. Add nullable user_id to existing resumes & analyses tables
alter table public.resumes
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table public.analyses
  add column if not exists user_id uuid references auth.users(id) on delete cascade;

create index if not exists idx_resumes_user_id on public.resumes(user_id);
create index if not exists idx_analyses_user_id on public.analyses(user_id);

-- 3. Guest IP rate-limit tracking (salted SHA-256 hash only, never raw IP)
create table if not exists public.guest_ip_usage (
  ip_hash text primary key,
  last_analysis_at timestamptz not null default now()
);

alter table public.guest_ip_usage enable row level security;
-- No anon/authenticated policies on guest_ip_usage: service_role only.

-- 4. Row-Level Security: users can only select their own rows
drop policy if exists "Allow anon read analyses" on public.analyses;

drop policy if exists "resumes_select_own" on public.resumes;
create policy "resumes_select_own" on public.resumes
  for select to authenticated
  using (auth.uid() = user_id);

drop policy if exists "analyses_select_own" on public.analyses;
create policy "analyses_select_own" on public.analyses
  for select to authenticated
  using (auth.uid() = user_id);

