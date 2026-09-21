"""Country rules API route.

Exposes country format guidelines, date formats, section ordering, and visa terms.
"""

from __future__ import annotations

from fastapi import APIRouter
from engine.country import get_country_rules, load_all_country_rules

router = APIRouter()


@router.get("/country/rules")
async def list_country_rules() -> dict:
    rules = load_all_country_rules()
    return {code: r.model_dump(mode="json") for code, r in rules.items()}


@router.get("/country/rules/{code}")
async def get_country_rule(code: str) -> dict:
    rule = get_country_rules(code)
    return rule.model_dump(mode="json")
