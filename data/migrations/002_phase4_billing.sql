-- ============================================================================
-- PHASE 4 MIGRATION: Checkout Sessions, Subscriptions, Usage Events & Stripe
-- ============================================================================
-- Run this migration in the Supabase SQL Editor after Phase 1 migration.
-- ============================================================================

create table if not exists public.checkout_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id text not null check (plan_id in ('pass')),
  amount_cents integer not null check (amount_cents >= 0),
  currency text not null default 'USD' check (currency in ('USD', 'KHR')),
  status text not null default 'pending'
    check (status in ('pending', 'paid', 'expired', 'canceled')),
  provider text not null check (provider in ('stripe_sandbox', 'mock')),
  provider_ref text unique,            -- Stripe Checkout Session ID (cs_test_...) or mock ref
  checkout_url text,                   -- Stripe hosted Checkout URL, null for mock
  expires_at timestamptz not null default (now() + interval '30 minutes'),
  paid_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  plan_id text not null check (plan_id in ('pass', 'campus')),
  current_period_start timestamptz not null default now(),
  current_period_end timestamptz not null,
  provider text not null default 'mock' check (provider in ('stripe_sandbox', 'mock', 'manual')),
  checkout_session_id uuid unique references public.checkout_sessions(id),
  created_at timestamptz not null default now()
);

-- Safe schema reconciliation if checkout_sessions or subscriptions existed from an earlier migration
alter table public.checkout_sessions
  add column if not exists amount_cents integer not null default 500,
  add column if not exists provider text not null default 'mock',
  add column if not exists provider_ref text unique,
  add column if not exists checkout_url text;

alter table public.checkout_sessions
  drop column if exists bill_number,
  drop column if exists amount_minor,
  drop column if exists recipient_bakong_id,
  drop column if exists qr_payload,
  drop column if exists qr_md5,
  drop column if exists nbc_transaction_hash;

alter table public.checkout_sessions
  drop constraint if exists checkout_sessions_status_check,
  drop constraint if exists checkout_sessions_provider_check;

update public.checkout_sessions
set status = 'pending'
where status = 'unpaid';

alter table public.checkout_sessions
  add constraint checkout_sessions_status_check
    check (status in ('pending', 'paid', 'expired', 'canceled')),
  add constraint checkout_sessions_provider_check
    check (provider in ('stripe_sandbox', 'mock'));

alter table public.subscriptions
  add column if not exists provider text not null default 'mock';

alter table public.subscriptions
  drop constraint if exists subscriptions_provider_check;

alter table public.subscriptions
  add constraint subscriptions_provider_check
    check (provider in ('stripe_sandbox', 'mock', 'manual'));

create table if not exists public.usage_events (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('analysis', 'rewrite')),
  created_at timestamptz not null default now()
);

-- Stripe webhook events already processed (Stripe can deliver the same event more than once)
create table if not exists public.stripe_events (
  id text primary key,                 -- Stripe event ID (evt_...)
  type text not null,
  received_at timestamptz not null default now()
);

create index if not exists usage_events_user_kind_time
  on public.usage_events (user_id, kind, created_at desc);
create index if not exists subscriptions_user_end
  on public.subscriptions (user_id, current_period_end desc);

alter table public.checkout_sessions enable row level security;
alter table public.subscriptions enable row level security;
alter table public.usage_events enable row level security;
alter table public.stripe_events enable row level security;   -- no policies: server only

drop policy if exists "checkout_select_own" on public.checkout_sessions;
create policy "checkout_select_own" on public.checkout_sessions
  for select using (auth.uid() = user_id);

drop policy if exists "subscriptions_select_own" on public.subscriptions;
create policy "subscriptions_select_own" on public.subscriptions
  for select using (auth.uid() = user_id);

drop policy if exists "usage_select_own" on public.usage_events;
create policy "usage_select_own" on public.usage_events
  for select using (auth.uid() = user_id);

-- No insert/update/delete policies on purpose.
-- Only FastAPI (service role, bypasses RLS) can write these tables.
-- Users must never be able to grant themselves a plan.
