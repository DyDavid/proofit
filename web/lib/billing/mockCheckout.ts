/**
 * Mock payment processor for Proofit demo mode.
 *
 * Simulates a realistic payment gateway with artificial latency, field validation,
 * and test card responses without making external network calls or charging money.
 * Strictly adheres to security standards: never logs or stores full card numbers or CVCs.
 */

export interface MockPaymentInput {
  cardNumber: string;
  expiry: string;
  cvc: string;
  cardholderName?: string;
}

export interface MockPaymentSuccess {
  success: true;
  last4: string;
  transactionId: string;
  planId: "pass";
  amountCents: number;
  currency: string;
}

export interface MockPaymentFailure {
  success: false;
  error: string;
  code: "declined" | "insufficient_funds" | "invalid_card" | "invalid_expiry" | "invalid_cvc";
}

export type MockPaymentResult = MockPaymentSuccess | MockPaymentFailure;

/** Strips all non-digit characters from a card string. */
export function sanitizeDigits(value: string): string {
  return value.replace(/\D/g, "");
}

/** Formats digits into groups of 4 separated by spaces (e.g. "4242 4242 4242 4242"). */
export function formatCardNumber(value: string): string {
  const digits = sanitizeDigits(value).slice(0, 16);
  const parts: string[] = [];
  for (let i = 0; i < digits.length; i += 4) {
    parts.push(digits.slice(i, i + 4));
  }
  return parts.join(" ");
}

/** Formats digits into MM/YY with an automatic slash. */
export function formatExpiry(value: string): string {
  const digits = sanitizeDigits(value).slice(0, 4);
  if (digits.length >= 3) {
    return `${digits.slice(0, 2)}/${digits.slice(2, 4)}`;
  }
  return digits;
}

/** Validates whether an expiry string (MM/YY) represents a valid future month. */
export function isValidFutureExpiry(expiry: string): boolean {
  const match = expiry.trim().match(/^(\d{2})\/(\d{2})$/);
  if (!match) return false;

  const month = parseInt(match[1], 10);
  const year2Digits = parseInt(match[2], 10);

  if (month < 1 || month > 12) return false;

  const fullYear = 2000 + year2Digits;
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth() + 1; // 1-indexed

  if (fullYear < currentYear) return false;
  if (fullYear === currentYear && month < currentMonth) return false;

  // Reasonable future ceiling (e.g. up to 25 years in future)
  if (fullYear > currentYear + 25) return false;

  return true;
}

/** Validates CVC (3 or 4 digits). */
export function isValidCvc(cvc: string): boolean {
  const digits = sanitizeDigits(cvc);
  return digits.length === 3 || digits.length === 4;
}

/**
 * Executes a simulated checkout request.
 * Resolves after a 1.6–1.8s delay to replicate a real gateway call.
 */
export async function mockCheckout(input: MockPaymentInput): Promise<MockPaymentResult> {
  // Simulate network round-trip delay
  await new Promise((resolve) => setTimeout(resolve, 1700));

  const digits = sanitizeDigits(input.cardNumber);

  // 1. Validate card number length
  if (digits.length !== 16) {
    return {
      success: false,
      error: "Please enter a complete 16-digit card number.",
      code: "invalid_card",
    };
  }

  // 2. Validate expiry
  if (!isValidFutureExpiry(input.expiry)) {
    return {
      success: false,
      error: "Enter a valid future expiration date (MM/YY).",
      code: "invalid_expiry",
    };
  }

  // 3. Validate CVC
  if (!isValidCvc(input.cvc)) {
    return {
      success: false,
      error: "Enter a valid 3 or 4-digit CVC code.",
      code: "invalid_cvc",
    };
  }

  // 4. Test card behaviors
  if (digits === "4000000000000002") {
    return {
      success: false,
      error: "Your card was declined. In demo mode, use 4242 4242 4242 4242.",
      code: "declined",
    };
  }

  if (digits === "4000000000009995") {
    return {
      success: false,
      error: "Your card has insufficient funds. In demo mode, use 4242 4242 4242 4242.",
      code: "insufficient_funds",
    };
  }

  // Demo success card
  if (digits === "4242424242424242") {
    return {
      success: true,
      last4: "4242",
      transactionId: `mock_ch_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
      planId: "pass",
      amountCents: 500,
      currency: "USD",
    };
  }

  // Any other card number is declined with demo guidance
  return {
    success: false,
    error: "Your card was declined. In demo mode, use 4242 4242 4242 4242.",
    code: "declined",
  };
}

