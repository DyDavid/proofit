import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../lib/authRedirect.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext },
}).outputText;
const { sanitizeNextPath } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

test("rejects external destinations and browser URL normalization tricks", () => {
  for (const path of [
    "https://attacker.example", "//attacker.example", "/\\attacker.example/login",
    "/\t/attacker.example", "/\n/attacker.example", "/a/..//attacker.example",
    "javascript:alert(1)", "/analyze\u007f", null, "",
  ]) {
    assert.equal(sanitizeNextPath(path), "/analyze", String(path));
  }
  // searchParams decodes attacker-supplied URL values before calling the helper.
  const next = new URL("https://app.example/login?next=%2F%5Cattacker.example").searchParams.get("next");
  assert.equal(sanitizeNextPath(next), "/analyze");
});

test("preserves useful local destinations and always returns a same-origin path", () => {
  for (const path of ["/dashboard", "/analyze?country=KH", "/account#settings", "/a/../results?id=123"]) {
    const result = sanitizeNextPath(path);
    assert.equal(new URL(result, "https://app.example").origin, "https://app.example");
  }
  assert.equal(sanitizeNextPath("/analyze?country=KH"), "/analyze?country=KH");
  assert.equal(sanitizeNextPath("/a/../results?id=123"), "/results?id=123");
});
