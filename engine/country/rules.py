"""F6 — the country-rules config, its model, and the destination resolver.

OWNER: **Person B** (PERSON_B_PLAN_v2.md §2: B owns the config; A owns the
visa-signal *extraction prompt* if they have time — a split to confirm at CP2,
which has not happened yet).

PERSON_B_PLAN_v2.md §5 Phase 4 task 4. Three things live here:

1. :class:`CountryRules` — one destination market's resume conventions.
2. :func:`load_country_rules` — reads and validates ``rules.json`` once per process.
3. :func:`rules_for` — resolves whatever destination string the caller happens to
   hold into a rule set, or ``None``.

Why (3) is not trivial
----------------------
This codebase carries three different spellings of the same destination:

* ``AnalyzeForm.tsx`` — what the browser POSTs: ``"cambodia"``, ``"singapore"``,
  ``"japan"``, ``"usRemote"``, ``"australia"``, ``"other"``.
* ``Job.country`` — what Person A's normalizer emits: ISO 3166-1 alpha-2
  (``"KH"``, ``"SG"``, ``"JP"``, ``"AU"``) or the ``"REMOTE"`` sentinel.
* PERSON_B_PLAN_v2.md Phase 4 — prose: "SG, JP, US-remote".

``AnalysisRecord.country`` stores the browser's string verbatim and unvalidated
(``api/store.py``), so by the time anything wants rules it may hold any of the
three. :func:`rules_for` is the single place that reconciles them; nothing else
should be doing string surgery on a country.

Canonical keys here are the ISO-style codes, not the browser's camelCase: those
are a presentation detail of one client and have no business reaching engine
config.

Adding a market
---------------
Content — page length, tone notes, visa terms — is pure config: edit
``rules.json``, no new code. Adding a whole new *country* additionally means
extending :data:`CountryCode`, which is deliberate: the set is closed in the UI
(``COUNTRY_KEYS`` is an ``as const`` tuple) and closed in ``Job.country``, so
letting it be open only here would hide a typo instead of failing on it.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "EXPECTED_COUNTRY_CODES",
    "RULES_PATH",
    "CountryCode",
    "CountryRules",
    "CountryRulesFile",
    "all_country_rules",
    "load_country_rules",
    "normalize_destination",
    "rules_for",
]

#: The destination markets this project supports. ``REMOTE`` is the United States
#: remote market rather than "anywhere remote": it is the sentinel ``Job.country``
#: already uses, and every remote JD collected so far carries US work-authorisation
#: language, which is what makes the rules meaningful.
CountryCode = Literal["KH", "SG", "JP", "AU", "REMOTE"]

#: Every code the config file must define. Matches the five real destinations the
#: Analyze screen offers; the UI's sixth option, "other", resolves to ``None``.
EXPECTED_COUNTRY_CODES: tuple[CountryCode, ...] = ("KH", "SG", "JP", "AU", "REMOTE")

RULES_PATH = Path(__file__).resolve().parent / "rules.json"

#: Everything that is not a letter or a digit. Lets "usRemote", "US-REMOTE",
#: "us_remote" and "US Remote" all reduce to the same lookup key.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class _Base(BaseModel):
    """Shared config, following ``engine/normalize/schema.py``'s ``_Base``.

    Redeclared rather than imported: that class is private, and its module is
    Person A's to replace wholesale at CP1. Copying the settings is cheaper than
    coupling F6 to a file that is contractually going to be overwritten.

    ``frozen=True`` is the one addition. These models are parsed once and handed
    to every caller for the life of the process, so an accidental write in a UI
    code path would silently change what every later request sees. Config that is
    shared and cached should not be writable.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


def normalize_destination(value: str) -> str:
    """Reduce a destination string to its lookup key.

    Lowercases and drops every non-alphanumeric character, so the browser's
    ``"usRemote"``, the schema's ``"REMOTE"``, and a hand-typed ``"US-Remote"``
    all collapse onto comparable keys.
    """
    return _NON_ALNUM.sub("", value.strip().lower())


class CountryRules(_Base):
    """One destination market's resume conventions.

    Every field is required. A key missing from ``rules.json`` raises here rather
    than rendering as an empty line in the Phase 4.5 country checklist.
    """

    code: CountryCode = Field(description="Canonical destination code. Unique within the file.")
    display_name: str = Field(
        min_length=1,
        description="Shown to the user, e.g. 'United States (remote)'.",
    )
    aliases: list[str] = Field(
        min_length=1,
        description=(
            "Every spelling that should resolve here — the browser's key, the ISO "
            "code, and common long forms. Compared after normalize_destination, so "
            "case and separators do not matter. Must not collide across countries."
        ),
    )

    max_pages: int = Field(
        ge=1,
        le=4,
        description="Longest resume this market reads without prejudice.",
    )
    page_length_note: str = Field(min_length=1)

    include_photo: bool = Field(
        description=(
            "Whether a photo is expected. The sharpest difference between these "
            "markets: Japan's rirekisho requires one, Singapore and the US advise "
            "against one on anti-discrimination grounds."
        )
    )
    photo_note: str = Field(min_length=1)

    include_personal_details: list[str] = Field(
        min_length=1,
        description="Details this market expects to see.",
    )
    omit_personal_details: list[str] = Field(
        min_length=1,
        description="Details to leave out — often because including them invites discrimination.",
    )

    date_format: str = Field(min_length=1, description="Convention, e.g. 'MMM YYYY'.")
    date_format_example: str = Field(min_length=1, description="The same date, written out.")

    section_order: list[str] = Field(
        min_length=1,
        description="Section headings, in the order this market expects to read them.",
    )
    tone_notes: list[str] = Field(
        min_length=1,
        description=(
            "Register and structure guidance. Bound by BRAND.md §6 — this is "
            "rendered to users."
        ),
    )
    visa_terms: list[str] = Field(
        min_length=1,
        description=(
            "Work-authorisation vocabulary to look for in a JD from this market. "
            "Stored lowercase because it is matched against lowercased JD text."
        ),
    )


class CountryRulesFile(_Base):
    """The parsed ``rules.json``."""

    version: str = Field(min_length=1)
    countries: list[CountryRules] = Field(min_length=1)

    @model_validator(mode="after")
    def _codes_and_aliases_are_unambiguous(self) -> CountryRulesFile:
        """No duplicate code, and no alias claimed by two countries.

        A collision would make :func:`rules_for` return whichever country the file
        happened to list first — a bug that would show up as the wrong country's
        checklist on screen, with nothing in the logs.
        """
        codes = [c.code for c in self.countries]
        duplicates = {code for code in codes if codes.count(code) > 1}
        if duplicates:
            raise ValueError(f"duplicate country code(s) in rules.json: {sorted(duplicates)}")

        claimed_by: dict[str, CountryCode] = {}
        for country in self.countries:
            for alias in [country.code, *country.aliases]:
                key = normalize_destination(alias)
                if not key:
                    raise ValueError(f"{country.code} has an empty alias")
                owner = claimed_by.get(key)
                if owner is not None and owner != country.code:
                    raise ValueError(
                        f"alias {alias!r} is claimed by both {owner} and {country.code}"
                    )
                claimed_by[key] = country.code
        return self


@lru_cache(maxsize=1)
def load_country_rules() -> CountryRulesFile:
    """Read and validate ``rules.json``. Cached: read once per process.

    Lazy rather than at import time, so a malformed file surfaces as a normal
    exception at the first call — testable, and it keeps importing this module
    free of file I/O. Call it once during API startup if you want the failure at
    boot rather than on the first request.
    """
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return CountryRulesFile.model_validate(raw)


def all_country_rules() -> dict[CountryCode, CountryRules]:
    """Every rule set, indexed by canonical code.

    Deliberately *not* cached: the expensive half — reading and validating the
    file — already is, and rebuilding a five-entry dict costs nothing. Handing
    every caller the same mutable dict would mean one ``.pop()`` anywhere
    corrupts the config for the rest of the process.
    """
    return {country.code: country for country in load_country_rules().countries}


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, CountryRules]:
    """Normalized alias (and code) → rule set."""
    index: dict[str, CountryRules] = {}
    for country in load_country_rules().countries:
        for alias in [country.code, *country.aliases]:
            index[normalize_destination(alias)] = country
    return index


def rules_for(destination: str | None) -> CountryRules | None:
    """Resolve any destination spelling to its rule set.

    Accepts the browser's key (``"usRemote"``), the canonical code (``"REMOTE"``),
    or a long form (``"United States"``), in any case and with any separators.

    Returns ``None`` — never raises, never guesses — for the UI's ``"other"``
    option, for an empty value, and for anything unrecognised. A missing rule set
    means the country checklist is not shown; it does not mean the analysis failed,
    so this is a normal outcome rather than an error.
    """
    if not destination:
        return None
    return _alias_index().get(normalize_destination(destination))
