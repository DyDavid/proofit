-- Review and apply after 008, before deploying the six-phase security changes.
begin;

create table public.resource_request_buckets (
  scope text not null check (scope in ('jobs', 'auth')),
  subject text not null,
  hits timestamptz[] not null check (cardinality(hits) <= 10000),
  expires_at timestamptz not null,
  primary key (scope, subject)
);
create index resource_request_expiry on public.resource_request_buckets(scope, expires_at);
alter table public.resource_request_buckets enable row level security;
revoke all on table public.resource_request_buckets from public, anon, authenticated;
grant all on table public.resource_request_buckets to service_role;

create function public.admit_resource_request(
  p_scope text, p_subject text, p_limit integer, p_global_limit integer
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_now timestamptz;
  v_client timestamptz[];
  v_global timestamptz[];
begin
  if p_scope is null or p_scope not in ('jobs', 'auth') or p_subject is null
      or length(p_subject) < 1 or length(p_subject) > 128 or p_subject = '*'
      or p_limit is null or p_global_limit is null or p_limit < 0 or p_global_limit < 0
      or p_limit > 10000 or p_global_limit > 10000 then
    raise exception 'Invalid resource admission';
  end if;
  if p_limit = 0 or p_global_limit = 0 then
    return jsonb_build_object('allowed', false);
  end if;
  perform pg_advisory_xact_lock(hashtext('resource_admission:' || p_scope));
  v_now := clock_timestamp();
  delete from public.resource_request_buckets where (scope, subject) in (
    select scope, subject from public.resource_request_buckets
    where scope = p_scope and expires_at <= v_now limit 1000 for update skip locked
  );
  select array(select h from unnest(hits) h where h > v_now - interval '1 minute')
    into v_client from public.resource_request_buckets where scope = p_scope and subject = p_subject;
  select array(select h from unnest(hits) h where h > v_now - interval '1 minute')
    into v_global from public.resource_request_buckets where scope = p_scope and subject = '*';
  v_client := coalesce(v_client, array[]::timestamptz[]);
  v_global := coalesce(v_global, array[]::timestamptz[]);
  if cardinality(v_client) >= p_limit or cardinality(v_global) >= p_global_limit then
    return jsonb_build_object('allowed', false);
  end if;
  if not exists (select 1 from public.resource_request_buckets where scope = p_scope and subject = p_subject)
      and (select count(*) from public.resource_request_buckets where scope = p_scope) >= 5000 then
    return jsonb_build_object('allowed', false);
  end if;
  insert into public.resource_request_buckets(scope, subject, hits, expires_at) values
    (p_scope, p_subject, array_append(v_client, v_now), v_now + interval '1 minute'),
    (p_scope, '*', array_append(v_global, v_now), v_now + interval '1 minute')
    on conflict (scope, subject) do update set hits = excluded.hits, expires_at = excluded.expires_at;
  return jsonb_build_object('allowed', true);
end;
$$;

-- Serialize insert/dedup/cleanup/capacity checking in a single transaction.
create function public.submit_bounded_job(
  p_id text, p_hash text, p_raw text, p_source text, p_max_unused integer, p_retention_hours integer
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_job public.jobs%rowtype;
  v_now timestamptz;
begin
  if p_id is null or length(p_id) > 100 or p_hash is null or length(p_hash) > 128
      or p_raw is null or length(p_raw) > 100000 or p_source is null or p_source not in ('text', 'url')
      or p_max_unused is null or p_max_unused < 1 or p_max_unused > 10000
      or p_retention_hours is null or p_retention_hours < 1 or p_retention_hours > 168 then
    raise exception 'Invalid job submission';
  end if;
  perform pg_advisory_xact_lock(hashtext('bounded_job_storage'));
  v_now := clock_timestamp();
  delete from public.jobs where id in (
    select j.id from public.jobs j
    where j.created_at <= v_now - p_retention_hours * interval '1 hour'
      and not exists (select 1 from public.analyses a where a.job_id = j.id)
    order by j.created_at limit 1000 for update of j skip locked
  );
  select * into v_job from public.jobs where content_hash = p_hash;
  if found then
    return jsonb_build_object('allowed', true, 'cached', true, 'job', to_jsonb(v_job));
  end if;
  if (select count(*) from (select j.id from public.jobs j
      where not exists (select 1 from public.analyses a where a.job_id = j.id)
      limit p_max_unused) unused) >= p_max_unused then
    return jsonb_build_object('allowed', false);
  end if;
  insert into public.jobs(id, content_hash, source, raw, created_at)
    values (p_id, p_hash, p_source, p_raw, v_now) returning * into v_job;
  return jsonb_build_object('allowed', true, 'cached', false, 'job', to_jsonb(v_job));
end;
$$;

-- Completion ledger and entitlement mutation commit together. An exception or a
-- worker crash rolls back everything, so redelivery is always eligible to retry.
-- Legacy markers have unknown outcomes: replay them once through idempotent grants.
alter table public.stripe_events add column processed_at timestamptz;
create function public.process_stripe_checkout_event(
  p_event_id text, p_type text, p_provider_ref text,
  p_user_id text, p_amount integer, p_currency text
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  v_session public.checkout_sessions%rowtype;
begin
  if p_event_id is null or length(p_event_id) < 1 or length(p_event_id) > 255
      or p_type is null or length(p_type) > 255 then
    raise exception 'Invalid payment event';
  end if;
  perform pg_advisory_xact_lock(hashtext('stripe_event:' || p_event_id));
  if exists (select 1 from public.stripe_events where id = p_event_id and processed_at is not null) then
    return jsonb_build_object('processed', false);
  end if;
  if p_type in ('checkout.session.completed', 'checkout.session.expired') then
    select * into v_session from public.checkout_sessions where provider_ref = p_provider_ref;
    if not found then
      -- A checkout creation transaction may still be saving its provider reference.
      raise exception 'Payment checkout unavailable';
    end if;
    perform pg_advisory_xact_lock(hashtext('subscription:' || v_session.user_id::text));
    select * into v_session from public.checkout_sessions where id = v_session.id for update;
    if v_session.provider <> 'stripe_sandbox' then
      raise exception 'Invalid payment provider';
    end if;
    if p_type = 'checkout.session.completed' then
      if p_user_id is null or p_user_id <> v_session.user_id::text
          or p_amount is null or p_amount <> v_session.amount_cents
          or (p_currency is not null and upper(p_currency) <> v_session.currency) then
        raise exception 'Invalid payment details';
      end if;
      update public.checkout_sessions set status = 'paid', paid_at = coalesce(paid_at, clock_timestamp())
        where id = v_session.id;
      perform public.grant_checkout_pass(v_session.id, 30);
    elsif v_session.status = 'pending' then
      update public.checkout_sessions set status = 'expired' where id = v_session.id;
    end if;
  end if;
  insert into public.stripe_events(id, type, processed_at) values (p_event_id, p_type, clock_timestamp())
    on conflict (id) do update set processed_at = excluded.processed_at, type = excluded.type;
  return jsonb_build_object('processed', true);
end;
$$;

revoke all on function public.admit_resource_request(text, text, integer, integer) from public, anon, authenticated;
revoke all on function public.submit_bounded_job(text, text, text, text, integer, integer) from public, anon, authenticated;
revoke all on function public.process_stripe_checkout_event(text, text, text, text, integer, text) from public, anon, authenticated;
grant execute on function public.admit_resource_request(text, text, integer, integer) to service_role;
grant execute on function public.submit_bounded_job(text, text, text, text, integer, integer) to service_role;
grant execute on function public.process_stripe_checkout_event(text, text, text, text, integer, text) to service_role;
commit;
