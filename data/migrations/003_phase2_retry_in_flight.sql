-- ============================================================================
-- PHASE 2 MIGRATION: Retry In-Flight Tracking & Usage Reservations
-- ============================================================================
-- NOTE: Do not apply to production without review.
-- This migration supports multi-worker concurrency and duplicate in-flight
-- retry prevention when Supabase database persistence is enabled.
-- ============================================================================

-- 1. Add retried_by column to analyses table
alter table public.analyses
  add column if not exists retried_by text references public.analyses(id) on delete set null;

create index if not exists idx_analyses_retried_by on public.analyses(retried_by);
create index if not exists idx_analyses_in_flight on public.analyses(user_id, status)
  where status in ('queued', 'running');

-- 2. Usage reservations table for concurrency-safe quota reservation across workers
create table if not exists public.usage_reservations (
  id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('analysis', 'rewrite')),
  status text not null default 'active' check (status in ('active', 'committed', 'released')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 minutes')
);

create index if not exists idx_usage_reservations_active
  on public.usage_reservations(user_id, kind, status)
  where status = 'active';

alter table public.usage_reservations enable row level security;

drop policy if exists "usage_reservations_select_own" on public.usage_reservations;
create policy "usage_reservations_select_own" on public.usage_reservations
  for select using (auth.uid() = user_id);

