"""Tests for F6 Country Rules Loader.

Verifies completeness of country rules configuration for KH, SG, JP, US.
"""

from __future__ import annotations

import pytest

from engine.country import CountryRules, get_country_rules, load_all_country_rules


def test_load_all_country_rules() -> None:
    rules = load_all_country_rules()
    assert len(rules) >= 4
    for code in ["KH", "SG", "JP", "US"]:
        assert code in rules
        c_rule = rules[code]
        assert isinstance(c_rule, CountryRules)
        assert c_rule.max_pages in (1, 2)
        assert isinstance(c_rule.section_order, list)
        assert len(c_rule.section_order) > 0
        assert len(c_rule.visa_terms) > 0


def test_get_country_rules_fallback() -> None:
    kh = get_country_rules("KH")
    assert kh.country_code == "KH"

    sg = get_country_rules("sg")
    assert sg.country_code == "SG"

    # Unknown fallback to KH
    unknown = get_country_rules("XYZ")
    assert unknown.country_code == "KH"

    # Remote fallback to US
    remote = get_country_rules("US_REMOTE")
    assert remote.country_code == "US"
