"""F6 country rules: the config file, its loader, and the destination resolver.

PERSON_B_PLAN_v2.md §5 Phase 4 task 4 asks for "Loader + Pydantic model + test that
every country has every key". The model does most of that on its own — every field
is required and ``extra="forbid"`` is set, so a missing or misspelled key raises at
parse time rather than rendering as a blank line on the Results screen. What the
model *cannot* catch, and what these tests exist for:

* a country the UI offers being absent from the file entirely,
* a list key present but empty ("every key" is not satisfied by ``[]``),
* an alias colliding across two countries, which would make ``rules_for`` return
  whichever country happened to load first,
* the destination strings the web app actually sends failing to resolve,
* config copy that breaks BRAND.md §6's hard voice rules — this file is rendered to
  users in Phase 4.5, so the brand rules bind it exactly as they bind the UI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.country.rules import (
    EXPECTED_COUNTRY_CODES,
    CountryRules,
    all_country_rules,
    load_country_rules,
    normalize_destination,
    rules_for,
)

RULES_PATH = Path(__file__).resolve().parent.parent / "engine" / "country" / "rules.json"

#: Exactly the values `web/components/analyze/AnalyzeForm.tsx`'s COUNTRY_KEYS sends
#: to `POST /api/analyses`. "other" is deliberately excluded — it is the documented
#: no-rules fallback, asserted separately below.
WEB_COUNTRY_KEYS_WITH_RULES = ["cambodia", "singapore", "japan", "usRemote", "australia"]

#: The list-valued keys the plan names. Each must be present *and* non-empty.
REQUIRED_LIST_FIELDS = [
    "aliases",
    "include_personal_details",
    "omit_personal_details",
    "section_order",
    "tone_notes",
    "visa_terms",
]

#: The scalar keys the plan names.
REQUIRED_SCALAR_FIELDS = [
    "code",
    "display_name",
    "max_pages",
    "page_length_note",
    "include_photo",
    "photo_note",
    "date_format",
    "date_format_example",
]


# ── The file itself ───────────────────────────────────────────────────────────


def test_rules_file_parses_and_validates() -> None:
    """A malformed rules.json must fail loudly, here, not at demo time."""
    rules_file = load_country_rules()
    assert rules_file.version
    assert len(rules_file.countries) == len(EXPECTED_COUNTRY_CODES)


def test_every_expected_country_is_present() -> None:
    """Pydantic cannot catch a country that is simply absent from the list."""
    assert set(all_country_rules()) == set(EXPECTED_COUNTRY_CODES)


@pytest.mark.parametrize("code", EXPECTED_COUNTRY_CODES)
def test_every_country_has_every_key(code: str) -> None:
    """The plan's literal requirement, asserted field by field.

    Reads the raw JSON rather than the parsed model: the model would happily
    report a default for a key the file never supplied, which is exactly the
    failure this test is supposed to see.
    """
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    block = next(c for c in raw["countries"] if c["code"] == code)

    for field in REQUIRED_SCALAR_FIELDS + REQUIRED_LIST_FIELDS:
        assert field in block, f"{code} is missing the '{field}' key"

    expected_keys = set(REQUIRED_SCALAR_FIELDS + REQUIRED_LIST_FIELDS)
    assert set(block) == expected_keys, f"{code} has unexpected keys: {set(block) - expected_keys}"


@pytest.mark.parametrize("code", EXPECTED_COUNTRY_CODES)
@pytest.mark.parametrize("field", REQUIRED_LIST_FIELDS)
def test_no_list_field_is_empty(code: str, field: str) -> None:
    """'Every country has every key' is not satisfied by an empty list."""
    rules = all_country_rules()[code]
    assert getattr(rules, field), f"{code}.{field} is present but empty"


@pytest.mark.parametrize("code", EXPECTED_COUNTRY_CODES)
def test_page_length_is_plausible(code: str) -> None:
    rules = all_country_rules()[code]
    assert 1 <= rules.max_pages <= 4


# ── Aliases and the destination resolver ──────────────────────────────────────


def test_aliases_do_not_collide_across_countries() -> None:
    """A shared alias would make `rules_for` depend on file ordering."""
    seen: dict[str, str] = {}
    for code, rules in all_country_rules().items():
        for alias in rules.aliases:
            key = normalize_destination(alias)
            assert key not in seen, f"alias {alias!r} claimed by both {seen.get(key)} and {code}"
            seen[key] = code


@pytest.mark.parametrize("code", EXPECTED_COUNTRY_CODES)
def test_every_country_resolves_from_its_own_code(code: str) -> None:
    resolved = rules_for(code)
    assert resolved is not None
    assert resolved.code == code


@pytest.mark.parametrize("web_key", WEB_COUNTRY_KEYS_WITH_RULES)
def test_every_web_country_key_resolves(web_key: str) -> None:
    """The API stores the web app's key verbatim and unvalidated.

    `AnalyzeForm.tsx` sends "usRemote"; `Job.country` uses "REMOTE"; the plan calls
    it "US-remote". The resolver is the one place that reconciles them, so every
    key the UI can actually send must land on a real rule set.
    """
    assert rules_for(web_key) is not None


def test_other_and_unknown_destinations_resolve_to_none() -> None:
    """"other" is a deliberate no-rules fallback, not a bug."""
    assert rules_for("other") is None
    assert rules_for("atlantis") is None
    assert rules_for("") is None
    assert rules_for(None) is None


@pytest.mark.parametrize(
    "variant",
    ["SG", "sg", " sg ", "Singapore", "SINGAPORE", "singapore"],
)
def test_resolver_ignores_case_and_surrounding_whitespace(variant: str) -> None:
    resolved = rules_for(variant)
    assert resolved is not None
    assert resolved.code == "SG"


@pytest.mark.parametrize(
    "variant",
    ["REMOTE", "usRemote", "us-remote", "US_REMOTE", "us remote", "United States"],
)
def test_resolver_ignores_separators_on_the_remote_destination(variant: str) -> None:
    """The destination with the most spellings in this codebase gets its own test."""
    resolved = rules_for(variant)
    assert resolved is not None
    assert resolved.code == "REMOTE"


# ── Content the demo and the report depend on ─────────────────────────────────


def test_photo_expectation_differs_between_markets() -> None:
    """Phase 4's "done when": switching country visibly changes the checklist.

    Japan's rirekisho expects a photo; Singapore and the US both advise against one.
    If these ever agree, the country selector has nothing to show and the F6
    demo stops proving anything.
    """
    countries = all_country_rules()
    assert countries["JP"].include_photo is True
    assert countries["SG"].include_photo is False
    assert countries["REMOTE"].include_photo is False


@pytest.mark.parametrize("code", EXPECTED_COUNTRY_CODES)
def test_visa_terms_are_lowercased_for_matching(code: str) -> None:
    """These are matched against JD text, so they are stored match-ready."""
    for term in all_country_rules()[code].visa_terms:
        assert term == term.lower(), f"{code} visa term {term!r} is not lowercased"
        assert term.strip() == term


# ── BRAND.md §6, enforced in code rather than hoped for ───────────────────────

#: BRAND.md §6 "Never": hard rules, not style preferences. This config is rendered
#: to users in Phase 4.5, so it is bound by them. `\bATS\b` rather than a substring
#: search so that "formats" and "stats" do not trip it.
BANNED_PATTERNS = [
    (r"\bATS\b", "PROJECT_SPEC.md §2 / BRAND.md §6 forbid all ATS framing"),
    (r"\bguarantee", "BRAND.md §6: never promise an outcome"),
    (r"\bget hired\b", "BRAND.md §6: never promise an outcome"),
    (r"\bland the job\b", "BRAND.md §6: never promise an outcome"),
]


@pytest.mark.parametrize("pattern,reason", BANNED_PATTERNS)
def test_config_copy_obeys_brand_voice_rules(pattern: str, reason: str) -> None:
    text = RULES_PATH.read_text(encoding="utf-8")
    match = re.search(pattern, text, flags=re.IGNORECASE)
    assert match is None, f"rules.json contains {match.group(0)!r} — {reason}"


# ── The model's own guarantees ────────────────────────────────────────────────


def test_model_rejects_an_unknown_country_code() -> None:
    with pytest.raises(ValidationError):
        CountryRules.model_validate(
            {
                "code": "FR",
                "display_name": "France",
                "aliases": ["FR"],
                "max_pages": 2,
                "page_length_note": "n/a",
                "include_photo": False,
                "photo_note": "n/a",
                "include_personal_details": ["name"],
                "omit_personal_details": ["photo"],
                "date_format": "MMM YYYY",
                "date_format_example": "Jan 2024",
                "section_order": ["Experience"],
                "tone_notes": ["n/a"],
                "visa_terms": ["n/a"],
            }
        )


def test_model_rejects_unknown_fields() -> None:
    """`extra="forbid"`: a renamed key must fail here, not render as blank."""
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    block = dict(raw["countries"][0])
    block["favourite_colour"] = "lac"
    with pytest.raises(ValidationError):
        CountryRules.model_validate(block)


def test_loader_is_cached() -> None:
    """The file is read and validated once per process, not per request."""
    assert load_country_rules() is load_country_rules()
