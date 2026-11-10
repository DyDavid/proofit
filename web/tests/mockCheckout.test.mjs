import assert from "node:assert/strict";
import test from "node:test";
import {
  formatCardNumber,
  formatExpiry,
  isValidCvc,
  isValidFutureExpiry,
  mockCheckout,
  sanitizeDigits,
} from "../lib/billing/mockCheckout.ts";

test("sanitizeDigits removes non-digit characters", () => {
  assert.equal(sanitizeDigits("4242 4242-4242.4242"), "4242424242424242");
  assert.equal(sanitizeDigits("abc12d34"), "1234");
});

test("formatCardNumber groups into blocks of 4 up to 16 digits", () => {
  assert.equal(formatCardNumber("4242424242424242"), "4242 4242 4242 4242");
  assert.equal(formatCardNumber("4242"), "4242");
  assert.equal(formatCardNumber("42424"), "4242 4");
  assert.equal(formatCardNumber("42424242424242429999"), "4242 4242 4242 4242");
});

test("formatExpiry auto-formats MM/YY", () => {
  assert.equal(formatExpiry("12"), "12");
  assert.equal(formatExpiry("123"), "12/3");
  assert.equal(formatExpiry("1228"), "12/28");
});

test("isValidFutureExpiry checks month range and future date", () => {
  assert.equal(isValidFutureExpiry("13/28"), false); // invalid month
  assert.equal(isValidFutureExpiry("00/28"), false); // invalid month
  assert.equal(isValidFutureExpiry("01/20"), false); // past year
  assert.equal(isValidFutureExpiry("12/35"), true);  // future year
});

test("isValidCvc requires 3 or 4 digits", () => {
  assert.equal(isValidCvc("12"), false);
  assert.equal(isValidCvc("123"), true);
  assert.equal(isValidCvc("1234"), true);
  assert.equal(isValidCvc("12345"), false);
});

test("mockCheckout handles test card scenarios", async () => {
  // 1. Success card
  const ok = await mockCheckout({
    cardNumber: "4242 4242 4242 4242",
    expiry: "12/30",
    cvc: "123",
  });
  assert.equal(ok.success, true);
  if (ok.success) {
    assert.equal(ok.last4, "4242");
    assert.equal(ok.planId, "pass");
    assert.equal(ok.amountCents, 500);
  }

  // 2. Declined test card
  const declined = await mockCheckout({
    cardNumber: "4000 0000 0000 0002",
    expiry: "12/30",
    cvc: "123",
  });
  assert.equal(declined.success, false);
  if (!declined.success) {
    assert.equal(declined.code, "declined");
    assert.match(declined.error, /declined/i);
  }

  // 3. Insufficient funds test card
  const noFunds = await mockCheckout({
    cardNumber: "4000 0000 0000 9995",
    expiry: "12/30",
    cvc: "123",
  });
  assert.equal(noFunds.success, false);
  if (!noFunds.success) {
    assert.equal(noFunds.code, "insufficient_funds");
    assert.match(noFunds.error, /insufficient/i);
  }

  // 4. Invalid expiry
  const badExp = await mockCheckout({
    cardNumber: "4242 4242 4242 4242",
    expiry: "01/20",
    cvc: "123",
  });
  assert.equal(badExp.success, false);
  if (!badExp.success) {
    assert.equal(badExp.code, "invalid_expiry");
  }
});

