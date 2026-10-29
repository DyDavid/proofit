-- ============================================================================
-- PHASE 4 MIGRATION: Direct Individual Bakong KHQR, Subscriptions & Usage Events
-- ============================================================================
-- Run this migration in the Supabase SQL Editor after Phase 1 migration.
-- Do not apply without explicit user/teammate approval.
-- ============================================================================

create table if not exists public.checkout_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id text not null check (plan_id = 'pass'),
  bill_number text not null unique,
  amount_minor bigint not null check (amount_minor > 0),
  currency text not null check (currency in ('USD', 'KHR')),
  recipient_bakong_id text not null,
  qr_payload text not null,
  qr_md5 char(32) not null unique,
  status text not null default 'unpaid'
    check (status in ('unpaid', 'paid', 'expired')),
  nbc_transaction_hash text unique,
  expires_at timestamptz not null,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  check (expires_at > created_at)
);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id text not null check (plan_id in ('pass', 'campus')),
  current_period_start timestamptz not null,
  current_period_end timestamptz not null,
  checkout_session_id uuid unique references public.checkout_sessions(id),
  created_at timestamptz not null default now()
);

create table if not exists public.usage_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('analysis', 'rewrite')),
  created_at timestamptz not null default now()
);

create index if not exists usage_events_user_kind_time
  on public.usage_events (user_id, kind, created_at desc);
create index if not exists subscriptions_user_end
  on public.subscriptions (user_id, current_period_end desc);

alter table public.checkout_sessions enable row level security;
alter table public.subscriptions enable row level security;
alter table public.usage_events enable row level security;

drop policy if exists "checkout_select_own" on public.checkout_sessions;
create policy "checkout_select_own" on public.checkout_sessions
  for select using (auth.uid() = user_id);

drop policy if exists "subscriptions_select_own" on public.subscriptions;
create policy "subscriptions_select_own" on public.subscriptions
  for select using (auth.uid() = user_id);

drop policy if exists "usage_select_own" on public.usage_events;
create policy "usage_select_own" on public.usage_events
  for select using (auth.uid() = user_id);

-- No insert/update/delete policies for browser clients.
-- Only FastAPI (service role, bypasses RLS) may create orders or grant plans.
