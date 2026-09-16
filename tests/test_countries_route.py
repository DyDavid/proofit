"""`GET /api/countries` + `GET /api/countries/{destination}` (task 4 brief,
step 1) — the F6 country-rules config exposed over the API.

Written before `api/routes/countries.py` exists (TDD RED first). The route
itself is thin: `engine.country.rules` already owns every real decision —
which of this codebase's three spellings resolve to which market, and what
"no rules" means (`rules_for` returns `None`, never raises). These tests only
check that the route translates that faithfully into the API's envelope
(`docs/errors.md` §1) and never raises a bare `HTTPException`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app
from engine.country.rules import EXPECTED_COUNTRY_CODES

client = TestClient(app)


def test_list_countries_returns_all_five() -> None:
    res = client.get("/api/countries")
    assert res.status_code == 200
    body = res.json()
    codes = [c["code"] for c in body["countries"]]
    assert set(codes) == set(EXPECTED_COUNTRY_CODES)
    for country in body["countries"]:
        assert isinstance(country["display_name"], str)
        assert country["display_name"]


def test_get_country_returns_full_rules_for_a_known_destination() -> None:
    res = client.get("/api/countries/SG")
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "SG"
    assert body["display_name"] == "Singapore"
    # Every field CountryRules requires (engine/country/rules.py) must round-trip.
    for key in (
        "aliases",
        "max_pages",
        "page_length_note",
        "include_photo",
        "photo_note",
        "include_personal_details",
        "omit_personal_details",
        "date_format",
        "date_format_example",
        "section_order",
        "tone_notes",
        "visa_terms",
    ):
        assert key in body


def test_get_country_404s_for_other_with_country_rules_not_found() -> None:
    res = client.get("/api/countries/other")
    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] == "COUNTRY_RULES_NOT_FOUND"
    # The envelope's shape (docs/errors.md §1) — never a bare HTTPException.
    assert set(body["error"].keys()) == {"code", "message", "error_id"}


def test_get_country_404s_for_an_unrecognised_string() -> None:
    res = client.get("/api/countries/atlantis")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "COUNTRY_RULES_NOT_FOUND"


def test_get_country_resolves_the_browser_spelling_end_to_end() -> None:
    """`usRemote` is what `AnalyzeForm.tsx`'s COUNTRY_KEYS actually sends —
    the whole reason `rules_for` exists rather than a plain dict lookup on
    the canonical code."""
    res = client.get("/api/countries/usRemote")
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "REMOTE"
    assert body["display_name"] == "United States (remote)"


def test_get_country_resolves_a_long_form_name() -> None:
    res = client.get("/api/countries/Cambodia")
    assert res.status_code == 200
    assert res.json()["code"] == "KH"
