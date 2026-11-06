-- Apply after 006, before deploying the billing safety changes. Review before running.
begin;

create index if not exists checkout_sessions_pending_user
  on public.checkout_sessions(user_id, provider, expires_at) where status = 'pending';

-- Claim before contacting the payment provider. All workers reuse the same
-- pending session; a null provider_ref means its creator is still preparing it.
create or replace function public.reserve_checkout_session(
  p_session_id uuid, p_user_id uuid, p_provider text,
  p_amount_cents integer, p_currency text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_session public.checkout_sessions%rowtype;
  v_now timestamptz;
begin
  if p_session_id is null or p_user_id is null or p_provider is null
      or p_provider not in ('mock', 'stripe_sandbox')
      or p_amount_cents is null or p_amount_cents < 0
      or p_currency is null or p_currency not in ('USD', 'KHR') then
    raise exception 'Invalid checkout reservation';
  end if;
  perform pg_advisory_xact_lock(hashtext('checkout:' || p_user_id::text));
  v_now := clock_timestamp();
  select * into v_session from public.checkout_sessions
    where user_id = p_user_id and provider = p_provider
      and plan_id = 'pass' and status = 'pending' and expires_at > v_now
    order by created_at desc limit 1;
  if found then
    return jsonb_build_object('created', false, 'session', to_jsonb(v_session));
  end if;
  insert into public.checkout_sessions(
    id, user_id, plan_id, amount_cents, currency, status, provider, expires_at, created_at
  ) values (
    p_session_id, p_user_id, 'pass', p_amount_cents, p_currency, 'pending',
    p_provider, v_now + interval '30 minutes', v_now
  ) returning * into v_session;
  return jsonb_build_object('created', true, 'session', to_jsonb(v_session));
end;
$$;

-- Serialize grants too: retries grant once, and distinct early renewals queue
-- after the last purchased period rather than overlapping each other.
create or replace function public.grant_checkout_pass(p_session_id uuid, p_period_days integer)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_session public.checkout_sessions%rowtype;
  v_sub public.subscriptions%rowtype;
  v_start timestamptz;
  v_now timestamptz;
begin
  if p_period_days is null or p_period_days <= 0 then
    raise exception 'Invalid subscription period';
  end if;
  select * into v_session from public.checkout_sessions where id = p_session_id;
  if not found then
    raise exception 'Unknown checkout';
  end if;
  perform pg_advisory_xact_lock(hashtext('subscription:' || v_session.user_id::text));
  select * into v_session from public.checkout_sessions where id = p_session_id for update;
  if not found or v_session.status <> 'paid' then
    raise exception 'Checkout is not paid';
  end if;
  select * into v_sub from public.subscriptions where checkout_session_id = p_session_id;
  if found then
    return jsonb_build_object('subscription', to_jsonb(v_sub));
  end if;
  v_now := clock_timestamp();
  select greatest(v_now, max(current_period_end)) into v_start
    from public.subscriptions where user_id = v_session.user_id and current_period_end > v_now;
  insert into public.subscriptions(
    id, user_id, plan_id, current_period_start, current_period_end, provider, checkout_session_id, created_at
  ) values (
    gen_random_uuid(), v_session.user_id, v_session.plan_id,
    v_start, v_start + p_period_days * interval '1 day', v_session.provider, p_session_id, v_now
  ) returning * into v_sub;
  return jsonb_build_object('subscription', to_jsonb(v_sub));
end;
$$;

revoke all on function public.reserve_checkout_session(uuid, uuid, text, integer, text) from public, anon, authenticated;
revoke all on function public.grant_checkout_pass(uuid, integer) from public, anon, authenticated;
grant execute on function public.reserve_checkout_session(uuid, uuid, text, integer, text) to service_role;
grant execute on function public.grant_checkout_pass(uuid, integer) to service_role;

commit;
