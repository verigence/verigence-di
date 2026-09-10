from __future__ import annotations

import pytest

from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.insurance_cover import INSURANCE_COVER_SCHEMA

pytestmark = pytest.mark.no_docker


def test_insurance_cover_registry_resolves_the_dedicated_schema() -> None:
    assert get_schema("insurance_cover") is INSURANCE_COVER_SCHEMA


def test_insurance_cover_captures_agent_intermediary_misp_and_addons() -> None:
    # Business ask: Agent/Intermediary Details, Agent/Intermediary Code, MISP
    # code, and add-ons taken (zero dep, engine protection, etc.).
    keys = {field.key for field in INSURANCE_COVER_SCHEMA.fields}
    assert "agent_intermediary_name" in keys
    assert "agent_intermediary_code" in keys
    assert "misp_code" in keys
    assert "add_ons" in keys


def test_insurance_cover_agent_and_misp_fields_are_independent() -> None:
    # A policy can show either, both, or neither -- confirm none of the three
    # new fields are marked required (that would force a false positive on a
    # perfectly normal policy sold with none of them).
    by_key = {field.key: field for field in INSURANCE_COVER_SCHEMA.fields}
    for key in ("agent_intermediary_name", "agent_intermediary_code", "misp_code"):
        assert by_key[key].required is False
