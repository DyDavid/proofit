#!/usr/bin/env python3
"""Export the locked Pydantic schema as one JSON Schema document.

Step 1 of 2 in the type pipeline (PERSON_B_PLAN_v2.md §5 Phase 1.2):

    engine/normalize/schema.py          <- Person A's locked schema (source of truth)
      -> scripts/export_schema.py       <- YOU ARE HERE
      -> web/lib/schema.json
      -> json-schema-to-typescript@16
      -> web/lib/types.ts

Run it directly, from any working directory::

    python scripts/export_schema.py

or, more usually, let ``scripts/gen-types.sh`` run it with the repo venv.

------------------------------------------------------------------------------
WHY THE OUTPUT IS NORMALISED THE WAY IT IS
------------------------------------------------------------------------------
The CI staleness check is a plain ``git diff --exit-code`` on this file and on
``web/lib/types.ts``. That only works if two runs of the same schema produce two
byte-identical files, so everything here is deterministic:

* ``sort_keys=True``    -- key order never depends on Python dict insertion order.
* trailing newline      -- POSIX text file; keeps ``git diff`` from reporting
                           "\\ No newline at end of file" noise forever.
* no timestamps         -- nothing derived from the clock is written. A generated
                           file that embeds "now" is stale one second after it is
                           written, and the staleness check would fail on every
                           single CI run.
* explicit root title   -- json-schema-to-typescript names the root interface
                           after ``title``; pinning it keeps ``SchemaBundle`` the
                           stable public name in ``web/lib/types.ts``.

The one non-obvious transform is ``_strip_property_titles``. Pydantic auto-titles
*every* property ("Id", "Text", "Results", "Score", ...). json-schema-to-typescript
hoists each of those into its own exported alias, so the generated file grows from
12 honest interfaces to 78 aliases -- and, because ``Requirement.id`` and
``Evidence.id`` are both titled "Id", it disambiguates them into ``Id`` and ``Id1``.
Those numbered names are assigned in traversal order, so adding a model upstream can
silently renumber a type the UI imports. Property titles are annotations with no
validation meaning (JSON Schema 2020-12 §9.1), so dropping them changes nothing about
what the document validates and buys clean, collision-free, stable type names.

Model-level titles ARE kept -- they are what names the 11 interfaces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Resolve everything from this file, never from the caller's cwd, so that
# `python scripts/export_schema.py` and `python /abs/path/export_schema.py`
# behave identically.
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "web" / "lib" / "schema.json"

#: Pinned so the generated root interface in web/lib/types.ts is always
#: `SchemaBundle`, whatever Pydantic would have inferred.
ROOT_TITLE = "SchemaBundle"

#: Source file quoted in the generated banner and in this script's stdout.
SOURCE_REL = "engine/normalize/schema.py"


# ── JSON Schema traversal ────────────────────────────────────────────────────
# A schema-aware walker. The naive "delete every key called 'title'" is a bug:
# `Job.title` is a real field, and it lives at $defs/Job/properties/title, whose
# *key* is the string "title". Keys inside a `properties` map are field names, not
# keywords, so the walker must only ever recurse into their values.

#: Keywords whose value is a map of name -> subschema.
_MAP_OF_SCHEMAS = ("properties", "patternProperties", "$defs", "definitions")
#: Keywords whose value is a list of subschemas.
_LIST_OF_SCHEMAS = ("anyOf", "oneOf", "allOf", "prefixItems")
#: Keywords whose value is a single subschema.
_SINGLE_SCHEMA = ("items", "additionalProperties", "not", "contains", "propertyNames")


def _strip_property_titles(schema: Any, *, keep_title: bool) -> None:
    """Recursively drop auto-generated ``title`` annotations, in place.

    ``keep_title`` is True only for the root document and for the direct entries
    of ``$defs`` -- the schemas that become named TypeScript interfaces.
    """
    if not isinstance(schema, dict):
        return

    if not keep_title:
        schema.pop("title", None)

    for keyword in _MAP_OF_SCHEMAS:
        subschemas = schema.get(keyword)
        if isinstance(subschemas, dict):
            # Entries of $defs/definitions are named models; keep their titles.
            names_a_model = keyword in ("$defs", "definitions")
            for subschema in subschemas.values():
                _strip_property_titles(subschema, keep_title=names_a_model)

    for keyword in _LIST_OF_SCHEMAS:
        subschemas = schema.get(keyword)
        if isinstance(subschemas, list):
            for subschema in subschemas:
                _strip_property_titles(subschema, keep_title=False)

    for keyword in _SINGLE_SCHEMA:
        subschema = schema.get(keyword)
        # `additionalProperties: false` is a bool, not a schema -- isinstance guards it.
        if isinstance(subschema, dict):
            _strip_property_titles(subschema, keep_title=False)


def build_schema() -> dict[str, Any]:
    """Import the locked schema and return the normalised JSON Schema document."""
    # Importable whatever the cwd: `engine` is a flat-layout package at the repo
    # root (pyproject.toml [tool.setuptools].packages).
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from engine.normalize.schema import SCHEMA_VERSION, SchemaBundle
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise SystemExit(
            f"export_schema.py: cannot import {SOURCE_REL}: {exc}\n"
            f"  Expected repo root: {REPO_ROOT}\n"
            "  Fix: run with the repo venv, e.g. .venv/bin/python scripts/export_schema.py"
        ) from exc

    document: dict[str, Any] = SchemaBundle.model_json_schema()

    _strip_property_titles(document, keep_title=True)

    # Pinned after the walk so it cannot be stripped, and recorded so a reader of
    # schema.json can see which schema version produced it.
    document["title"] = ROOT_TITLE
    document["x-schema-version"] = SCHEMA_VERSION
    document["x-generated-by"] = f"scripts/export_schema.py from {SOURCE_REL}"

    return document


def main() -> int:
    document = build_schema()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    # newline="\n" so a Windows checkout cannot introduce CRLF and break the diff.
    OUTPUT_PATH.write_text(payload, encoding="utf-8", newline="\n")

    model_count = len(document.get("$defs", {}))
    rel_out = OUTPUT_PATH.relative_to(REPO_ROOT)
    print(
        f"export_schema.py: wrote {rel_out} "
        f"({model_count} models, {len(payload)} bytes, "
        f"schema version {document['x-schema-version']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
