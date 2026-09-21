"""Country Rules Config Loader.

Provides country-specific resume formatting rules and visa signal extraction terms.
"""

from __future__ import annotations

import json
from pathlib import Path
from pydantic import BaseModel, Field

_RULES_FILE = Path(__file__).parent / "rules.json"


class CountryRules(BaseModel):
    country_code: str = Field(..., description="ISO alpha-2 country code (e.g. KH, SG, JP, US).")
    name: str = Field(..., description="Display name of target country.")
    max_pages: int = Field(..., ge=1, le=5)
    photo_recommended: bool
    include_personal_details: bool
    date_format: str
    section_order: list[str]
    tone_notes: str
    visa_terms: list[str]


def load_all_country_rules() -> dict[str, CountryRules]:
    """Loads all country rules from rules.json."""
    if not _RULES_FILE.is_file():
        raise FileNotFoundError(f"Country rules file not found: {_RULES_FILE}")
    with open(_RULES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {code: CountryRules(**config) for code, config in data.items()}


def get_country_rules(country_code: str) -> CountryRules:
    """Returns CountryRules for a given country code, falling back to KH if unknown."""
    rules_map = load_all_country_rules()
    code = (country_code or "KH").upper()
    if code not in rules_map:
        # Fall back to US if REMOTE, else KH
        code = "US" if "REMOTE" in code else "KH"
    return rules_map[code]
