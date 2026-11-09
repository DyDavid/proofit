import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { setImmediate } from "node:timers/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../components/billing/PricingGrid.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const plans = ["free", "pass", "campus"].map((id) => ({ id }));

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

// Exercise the actual component's render/effect lifecycle without a browser or
// additional test dependencies. Child components are represented as JSX nodes.
function mount(t, { planQuery = null, plansPromise = Promise.resolve(plans), subscriptionPromise = Promise.resolve(null), configured = true } = {}) {
  const slots = [];
  const pendingEffects = [];
  const redirects = [];
  const checkouts = [];
  let cursor = 0;
  let dirty = true;
  let tree;
  let authCallback;
  let unsubscribed = false;
  const sameDeps = (a, b) => a && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const hooks = {
    useState(initial) {
      const index = cursor++;
      const slot = slots[index] ??= { value: initial };
      return [slot.value, (value) => {
        const next = typeof value === "function" ? value(slot.value) : value;
        if (!Object.is(next, slot.value)) { slot.value = next; dirty = true; }
      }];
    },
    useEffect(effect, deps) {
      const index = cursor++;
      const previous = slots[index];
      if (!sameDeps(previous?.deps, deps)) {
        const slot = slots[index] = { deps, cleanup: previous?.cleanup };
        pendingEffects.push(() => { slot.cleanup?.(); slot.cleanup = effect(); });
      }
    },
    useCallback(callback, deps) {
      const index = cursor++;
      if (!sameDeps(slots[index]?.deps, deps)) slots[index] = { deps, callback };
      return slots[index].callback;
    },
  };
  const router = { push: (path) => redirects.push(path) };
  const searchParams = { get: () => planQuery };
  const mocks = {
    react: hooks,
    "react/jsx-runtime": require("react/jsx-runtime"),
    "next/navigation": { useRouter: () => router, useSearchParams: () => searchParams },
    "@/lib/supabase/client": { createClient: () => configured ? { auth: {
      onAuthStateChange(callback) {
        authCallback = callback;
        return { data: { subscription: { unsubscribe() { unsubscribed = true; } } } };
      },
    } } : null },
    "@/lib/billing/api": {
      DEFAULT_PLANS: plans,
      fetchPlans: () => plansPromise,
      fetchSubscription: () => subscriptionPromise,
    },
  };
  for (const name of ["PricingCard", "CheckoutDialog", "CampusContactDialog"]) {
    mocks[`@/components/billing/${name}`] = { [name]: name };
  }
  const exports = {};
  runInNewContext(compiled, { exports, process: { env: {} }, require: (name) => {
    assert.ok(name in mocks, `Unexpected import: ${name}`);
    return mocks[name];
  } });
  const props = { onStartCheckout: (plan) => checkouts.push(plan.id) };
  function render() {
    let iterations = 0;
    while (dirty) {
      assert.ok(iterations++ < 20, "Render loop did not settle");
      dirty = false;
      cursor = 0;
      tree = exports.PricingGrid(props);
      pendingEffects.splice(0).forEach((effect) => effect());
    }
  }
  t.after(() => {
    slots.forEach((slot) => slot.cleanup?.());
    if (configured) assert.equal(unsubscribed, true);
  });
  render();
  return {
    redirects, checkouts,
    emit(event, userId = null) { authCallback(event, userId ? { user: { id: userId } } : null); render(); },
    card(id) { return tree.props.children[0].props.children.find((node) => node.props.plan.id === id).props; },
    async flush() { await setImmediate(); render(); },
  };
}

test("Get Pass waits for session restoration, then opens checkout even if plans are slow", async (t) => {
  const slowPlans = deferred();
  const app = mount(t, { plansPromise: slowPlans.promise });
  assert.equal(app.card("pass").disabled, true);
  assert.match(app.card("pass").ctaLabel, /Checking/);
  app.card("pass").onAction();
  assert.deepEqual(app.redirects, []);
  assert.equal(app.card("campus").disabled, false);

  app.emit("INITIAL_SESSION", "existing-user");
  await app.flush();
  assert.equal(app.card("pass").disabled, false);
  app.card("pass").onAction();
  assert.deepEqual(app.checkouts, ["pass"]);
  assert.deepEqual(app.redirects, []);
});

test("only a resolved signed-out session redirects, preserving the pass destination", async (t) => {
  const app = mount(t);
  app.emit("INITIAL_SESSION");
  await app.flush();
  app.card("pass").onAction();
  const url = new URL(app.redirects[0], "https://proofit.example");
  assert.equal(url.pathname, "/login");
  assert.equal(url.searchParams.get("next"), "/pricing?plan=pass");
});

test("pricing follows sign-in, token refresh, and sign-out on the same mounted page", async (t) => {
  const slowSubscription = deferred();
  const app = mount(t, { subscriptionPromise: slowSubscription.promise });
  app.emit("INITIAL_SESSION");
  app.emit("SIGNED_IN", "existing-user");
  app.emit("TOKEN_REFRESHED", "existing-user");
  app.card("pass").onAction();
  assert.deepEqual(app.checkouts, ["pass"]);
  assert.deepEqual(app.redirects, []);

  app.emit("SIGNED_OUT");
  slowSubscription.resolve({ plan_id: "pass" });
  await app.flush();
  app.card("pass").onAction();
  assert.equal(app.redirects.length, 1);
  assert.equal(app.card("free").ctaLabel, "Get started");
});

test("returning from login resumes the requested checkout once", async (t) => {
  const app = mount(t, { planQuery: "pass" });
  assert.deepEqual(app.checkouts, []);
  app.emit("INITIAL_SESSION", "existing-user");
  await app.flush();
  app.emit("TOKEN_REFRESHED", "existing-user");
  assert.deepEqual(app.checkouts, ["pass"]);
});

test("unconfigured auth resolves to the signed-out flow", async (t) => {
  const app = mount(t, { configured: false });
  await app.flush();
  assert.equal(app.card("pass").disabled, false);
  app.card("pass").onAction();
  assert.equal(app.redirects.length, 1);
});
