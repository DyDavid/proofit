#!/usr/bin/env node
/**
 * i18n parity check for web/messages/en.json and web/messages/km.json.
 * PERSON_B_PLAN_v2.md §5 Phase 1.6 and §7 "i18n Rules".
 *
 *   node scripts/i18n-check.mjs
 *
 * Reports, as ERRORS (exit 1):
 *   MISSING  - a key present in one locale and absent from the other. A missing
 *              key is not a cosmetic problem: next-intl throws at render time,
 *              so a Khmer user gets an error boundary where a label should be.
 *   EMPTY    - a value that is an empty or whitespace-only string. Renders as a
 *              blank button or a blank heading, which is worse than a missing
 *              key because nothing fails loudly.
 *
 * Reports, as a WARNING (exit 0, does not fail the build):
 *   UNTRANSLATED - a km value byte-identical to its en value. Usually a key that
 *              was copied across and never translated. It is only a warning
 *              because plenty of values are legitimately identical in both
 *              locales: the brand name "Proofit", and any value that is just a
 *              number (§7.5 keeps Arabic numerals in both locales).
 *
 * Output is one finding per line, prefixed with a fixed, greppable token, e.g.
 *
 *   node scripts/i18n-check.mjs | grep '^MISSING'
 */

import { readFileSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

// Resolved from this file, not from cwd, so it behaves the same when CI runs it
// from the repo root and when a developer runs it from web/.
const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(SCRIPT_DIR, "..");
const MESSAGES_DIR = join(REPO_ROOT, "web", "messages");

/** Locale files, in the order findings are reported. `en` is the default locale. */
const LOCALES = [
  { code: "en", path: join(MESSAGES_DIR, "en.json") },
  { code: "km", path: join(MESSAGES_DIR, "km.json") },
];

const rel = (p) => relative(REPO_ROOT, p) || p;

/** Findings that fail the build. */
const errors = [];
/** Findings that are reported but do not fail the build. */
const warnings = [];

/**
 * Flatten a nested message object into dotted key paths.
 *
 * `{ common: { nav: { home: "Home" } } }` -> `{ "common.nav.home": "Home" }`
 *
 * Arrays are indexed (`items.0`) so a list of strings is still comparable across
 * locales rather than silently treated as one opaque leaf.
 */
function flatten(value, prefix = "", out = new Map()) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => flatten(item, prefix ? `${prefix}.${index}` : String(index), out));
    return out;
  }
  if (value !== null && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, out);
    }
    return out;
  }
  out.set(prefix, value);
  return out;
}

/**
 * Load and parse one locale file.
 * Returns null and records an error rather than throwing, so a missing or
 * malformed file produces a readable message instead of a Node stack trace.
 */
function loadLocale({ code, path }) {
  if (!existsSync(path)) {
    errors.push(
      `NOFILE   ${code}  ${rel(path)}  -- message file does not exist yet. ` +
        `Create it with the next-intl key set from the project contract.`
    );
    return null;
  }

  let raw;
  try {
    raw = readFileSync(path, "utf8");
  } catch (cause) {
    errors.push(`NOFILE   ${code}  ${rel(path)}  -- cannot read file: ${cause.message}`);
    return null;
  }

  if (raw.trim() === "") {
    errors.push(`BADJSON  ${code}  ${rel(path)}  -- file is empty`);
    return null;
  }

  try {
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      errors.push(`BADJSON  ${code}  ${rel(path)}  -- top level must be a JSON object`);
      return null;
    }
    return flatten(parsed);
  } catch (cause) {
    errors.push(`BADJSON  ${code}  ${rel(path)}  -- invalid JSON: ${cause.message}`);
    return null;
  }
}

/** Byte-for-byte comparison of two values encoded as UTF-8. */
function bytesIdentical(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return a === b;
  return Buffer.compare(Buffer.from(a, "utf8"), Buffer.from(b, "utf8")) === 0;
}

/** Truncate a value for single-line output without breaking the alignment. */
function preview(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 48 ? `${text.slice(0, 45)}...` : text;
}

function main() {
  const [en, km] = LOCALES;

  console.log(`i18n-check: en = ${rel(en.path)}`);
  console.log(`i18n-check: km = ${rel(km.path)}`);

  const enKeys = loadLocale(en);
  const kmKeys = loadLocale(km);

  // Both files must load before parity can mean anything. Report what we know
  // and stop -- comparing against a null map would produce nonsense findings.
  if (enKeys === null || kmKeys === null) {
    console.log("");
    for (const line of errors) console.log(line);
    console.log("");
    console.log(
      `i18n-check: ${errors.length} error(s), 0 warning(s) -- ` +
        "cannot compare locales until both message files load."
    );
    console.log("FAIL");
    return 1;
  }

  const allKeys = [...new Set([...enKeys.keys(), ...kmKeys.keys()])].sort();

  for (const key of allKeys) {
    const inEn = enKeys.has(key);
    const inKm = kmKeys.has(key);

    if (inEn && !inKm) {
      errors.push(`MISSING  km  ${key}  -- present in en, absent from km`);
      continue;
    }
    if (inKm && !inEn) {
      errors.push(`MISSING  en  ${key}  -- present in km, absent from en`);
      continue;
    }

    const enValue = enKeys.get(key);
    const kmValue = kmKeys.get(key);

    // Empty values are checked per locale: one locale can be filled in while the
    // other is still a placeholder "".
    const enEmpty = typeof enValue === "string" && enValue.trim() === "";
    const kmEmpty = typeof kmValue === "string" && kmValue.trim() === "";
    if (enEmpty) errors.push(`EMPTY    en  ${key}  -- value is an empty string`);
    if (kmEmpty) errors.push(`EMPTY    km  ${key}  -- value is an empty string`);
    if (enEmpty || kmEmpty) continue;

    // Numeric-looking values are identical in both locales by design (§7.5:
    // numbers stay Arabic numerals), so they are not suspicious.
    const isNumericLiteral = typeof enValue === "string" && /^[\d\s.,%+-]+$/.test(enValue);

    if (bytesIdentical(enValue, kmValue) && !isNumericLiteral) {
      warnings.push(`WARN     untranslated  ${key}  -- km is byte-identical to en: "${preview(enValue)}"`);
    }
  }

  console.log("");
  if (errors.length === 0 && warnings.length === 0) {
    console.log(`i18n-check: ${allKeys.length} keys checked, no findings.`);
    console.log("OK");
    return 0;
  }

  for (const line of errors) console.log(line);
  for (const line of warnings) console.log(line);

  console.log("");
  console.log(
    `i18n-check: ${allKeys.length} keys checked, ` +
      `${errors.length} error(s), ${warnings.length} warning(s).`
  );

  if (errors.length > 0) {
    console.log("FAIL");
    return 1;
  }
  console.log("OK  (warnings do not fail the build)");
  return 0;
}

// Catch-all so an unforeseen problem still prints one clear line instead of a
// stack trace in the CI log.
try {
  process.exit(main());
} catch (cause) {
  console.error(`i18n-check: unexpected error: ${cause && cause.message ? cause.message : cause}`);
  process.exit(1);
}
