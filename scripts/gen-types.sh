#!/usr/bin/env bash
#
# Regenerate web/lib/types.ts from Person A's locked Pydantic schema.
# PERSON_B_PLAN_v2.md §5 Phase 1.2 / §2 "the contract between you", point 1.
#
#     engine/normalize/schema.py
#       -> scripts/export_schema.py  -> web/lib/schema.json
#       -> json-schema-to-typescript -> web/lib/types.ts
#
# Usage (from any working directory):
#
#     bash scripts/gen-types.sh
#
# The script is idempotent: running it twice leaves both outputs byte-identical,
# which is what lets CI assert freshness with a plain `git diff --exit-code`.
# Nothing derived from the clock is ever written into the outputs.

set -euo pipefail

# ── paths, resolved from the script itself so cwd is irrelevant ──────────────
SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON="$REPO_ROOT/.venv/bin/python"
EXPORT_PY="$SCRIPT_DIR/export_schema.py"
SCHEMA_JSON="$REPO_ROOT/web/lib/schema.json"
TYPES_TS="$REPO_ROOT/web/lib/types.ts"
SOURCE_PY="engine/normalize/schema.py"

# Pinned major version. json-schema-to-typescript changes its output formatting
# between majors, and a formatting change would look like schema drift to CI.
JSON2TS_PKG="json-schema-to-typescript@16"

# ── preflight ────────────────────────────────────────────────────────────────
if [[ ! -x "$PYTHON" ]]; then
  echo "gen-types.sh: repo venv interpreter not found at $PYTHON" >&2
  echo "  The venv is expected at <repo>/.venv (see the project setup notes)." >&2
  exit 1
fi

if [[ ! -f "$EXPORT_PY" ]]; then
  echo "gen-types.sh: missing $EXPORT_PY" >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "gen-types.sh: npx not found on PATH (Node.js is required)." >&2
  exit 1
fi

# export_schema.py resolves its own paths, but running from the repo root keeps
# `import engine.normalize.schema` working even without an editable install.
cd "$REPO_ROOT"

# ── step 1: Pydantic -> JSON Schema ──────────────────────────────────────────
echo "gen-types.sh: [1/3] exporting JSON Schema from $SOURCE_PY"
"$PYTHON" "$EXPORT_PY"

if [[ ! -f "$SCHEMA_JSON" ]]; then
  echo "gen-types.sh: expected $SCHEMA_JSON to exist after export_schema.py" >&2
  exit 1
fi

# Read back from the emitted document rather than importing again, so the banner
# can only ever describe the schema.json that is actually on disk.
SCHEMA_VERSION="$("$PYTHON" -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as fh:
    print(json.load(fh).get('x-schema-version', 'unknown'))
" "$SCHEMA_JSON")"

# ── step 2: JSON Schema -> TypeScript ────────────────────────────────────────
echo "gen-types.sh: [2/3] generating TypeScript with $JSON2TS_PKG"

TMP_DIR="$(mktemp -d)"
# Clean up on success, failure, and Ctrl-C alike; never leave a half-written
# types.ts behind for the web build to pick up.
trap 'rm -rf "$TMP_DIR"' EXIT
TMP_TS="$TMP_DIR/types.ts"

# --bannerComment "" suppresses the tool's own header so this script owns the
# single banner at the top of the file (no duplicated "DO NOT MODIFY" blocks).
npx --yes "$JSON2TS_PKG" \
  --input "$SCHEMA_JSON" \
  --output "$TMP_TS" \
  --bannerComment "" \
  --additionalProperties false

if [[ ! -s "$TMP_TS" ]]; then
  echo "gen-types.sh: $JSON2TS_PKG produced no output" >&2
  exit 1
fi

# ── step 3: prepend the banner, write atomically ─────────────────────────────
echo "gen-types.sh: [3/3] writing $(basename "$TYPES_TS")"

TMP_OUT="$TMP_DIR/out.ts"
mkdir -p "$(dirname "$TYPES_TS")"

{
  cat <<BANNER
/* eslint-disable */
/**
 * =============================================================================
 *  GENERATED - DO NOT EDIT BY HAND.  Run scripts/gen-types.sh
 * =============================================================================
 *
 *  Source of truth:  $SOURCE_PY
 *                    (Person A's locked Pydantic schema - PERSON_B_PLAN_v2.md
 *                    §2 "the contract between you": never hand-write a type that
 *                    already exists in the schema.)
 *
 *  Pipeline:         $SOURCE_PY
 *                      -> scripts/export_schema.py
 *                      -> web/lib/schema.json
 *                      -> $JSON2TS_PKG
 *                      -> web/lib/types.ts   (this file)
 *
 *  To change a type, edit $SOURCE_PY and run:
 *
 *      bash scripts/gen-types.sh
 *
 *  Every edit made directly to this file is destroyed on the next run, and CI
 *  fails the build when this file no longer matches the schema. If the live
 *  engine disagrees with the UI, fix the schema and the fixtures - not this file.
 *
 *  Schema version:   $SCHEMA_VERSION
 */

BANNER
  cat "$TMP_TS"
} >"$TMP_OUT"

# mv is atomic within a filesystem; readers never observe a partial file.
mv "$TMP_OUT" "$TYPES_TS"

echo "gen-types.sh: done."
echo "  schema : ${SCHEMA_JSON#"$REPO_ROOT"/}"
echo "  types  : ${TYPES_TS#"$REPO_ROOT"/}  ($(grep -c '^export ' "$TYPES_TS") exported types, schema version $SCHEMA_VERSION)"
