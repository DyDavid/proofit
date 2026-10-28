-- ============================================================================
-- MIGRATION 003: ABA PayWay & KHQR Integration
-- ============================================================================
-- Enables 'aba_payway' as a valid provider in checkout_sessions and subscriptions.
-- Adds optional columns for dynamic QR image and deep link.
-- ============================================================================

-- 1. Allow 'aba_payway' in checkout_sessions provider check constraint
alter table public.checkout_sessions
  drop constraint if exists checkout_sessions_provider_check;

alter table public.checkout_sessions
  add constraint checkout_sessions_provider_check
  check (provider in ('stripe_sandbox', 'mock', 'aba_payway'));

-- 2. Allow 'aba_payway' in subscriptions provider check constraint
alter table public.subscriptions
  drop constraint if exists subscriptions_provider_check;

alter table public.subscriptions
  add constraint subscriptions_provider_check
  check (provider in ('stripe_sandbox', 'mock', 'aba_payway', 'manual'));

-- 3. Dynamic QR storage columns (optional cache on the checkout record)
alter table public.checkout_sessions
  add column if not exists qr_string text,
  add column if not exists qr_image text,
  add column if not exists deeplink text;

