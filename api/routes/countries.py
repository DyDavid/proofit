"""`GET /api/countries` + `GET /api/countries/{destination}` (task 4: F6
country-rules config, over the API).

Deliberately thin: every real decision — which of this codebase's three
spellings of a destination resolve to which market, and what "no rules"
means — already lives in `engine.country.rules` and is fully tested there
(`tests/test_country_rules.py`). This module's only job is to translate
`rules_for`'s result into the API's envelope (`docs/errors.md` §1), never a
bare `HTTPException` (`api/errors.py`, `docs/errors.md` §1).
"""

from __future__ import annotations

from fastapi import APIRouter

from api.errors import ApiError
from engine.country.rules import all_country_rules, rules_for

router = APIRouter()


@router.get("/countries")
async def list_countries() -> dict:
    """Every market this app has rules for, in `rules.json`'s own order.

    The UI's sixth option, "other", is deliberately absent — it has no rules
    to list, the same reason `rules_for("other")` returns `None` rather than
    a stub entry.
    """
    countries = all_country_rules()
    return {
        "countries": [
            {"code": country.code, "display_name": country.display_name}
            for country in countries.values()
        ]
    }


@router.get("/countries/{destination}")
async def get_country(destination: str) -> dict:
    """One destination's full rule set.

    `destination` is resolved through `rules_for`, so the caller may spell it
    any of this codebase's three ways — the browser's `"usRemote"`, the
    schema's `"REMOTE"`, or a long form like `"United States"`. A 404 here
    (`"other"`, or anything unrecognised) is a normal outcome, not a server
    failure — `rules_for`'s own docstring — hence `COUNTRY_RULES_NOT_FOUND`
    rather than `INTERNAL`.
    """
    rules = rules_for(destination)
    if rules is None:
        raise ApiError(
            status_code=404,
            code="COUNTRY_RULES_NOT_FOUND",
            message=f"No country rules for destination={destination!r}.",
        )
    return rules.model_dump(mode="json")
