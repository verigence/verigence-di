from __future__ import annotations

import json

import pytest

from verigence.di.document_ai.adapter import ExtractionField
from verigence.di.document_ai.gemini_adapter import (
    _build_prompt,
    _parse_response,
    looks_like_phone_number,
)
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


# Confirmed live 2026-10-27: on a Generali Central policy the MISP line reads
# "Name: ADITYA MOTORS Contact Number: 7873999101 Code: MIBL/M&M/AAECA5786A/000"
# and an earlier read stored the contact number as the agent code.

_CODE_FIELDS = [ExtractionField(field_key="agent_intermediary_code"), ExtractionField(field_key="misp_code"),
                ExtractionField(field_key="agent_intermediary_name")]


@pytest.mark.parametrize("value", ["7873999101", "+91 78739 99101", "07873999101", "78739-99101", "18002200233",
                                   "1800-220-233", 7873999100])
def test_phone_numbers_are_recognised(value: object) -> None:
    assert looks_like_phone_number(value) is True


@pytest.mark.parametrize("value", ["MIBL/M&M/AAECA5786A/000", "BA0000123456", "IRDA/DB/123/45", "A011351AD04", "5786",
                                   "132/02/21/1027/MTP/3630160121"])
def test_real_codes_are_not_phone_numbers(value: str) -> None:
    assert looks_like_phone_number(value) is False


def test_a_phone_number_read_as_a_code_is_dropped_and_a_real_code_kept() -> None:
    raw = json.dumps({
        "agent_intermediary_code": {"value": "7873999100", "confidence": "high", "pageNo": 1},
        "misp_code": {"value": "MIBL/M&M/AAECA5786A/000", "confidence": "high", "pageNo": 1},
        "agent_intermediary_name": {"value": "ADITYA MOTORS", "confidence": "high", "pageNo": 1},
    })
    by_key = {r.field_key: r for r in _parse_response(raw, INSURANCE_COVER_SCHEMA, _CODE_FIELDS)}
    assert by_key["agent_intermediary_code"].raw_value is None
    assert by_key["misp_code"].raw_value == "MIBL/M&M/AAECA5786A/000"
    assert by_key["agent_intermediary_name"].raw_value == "ADITYA MOTORS"


def test_the_prompt_says_a_contact_number_is_never_a_code_and_names_the_current_insurer() -> None:
    prompt = _build_prompt(INSURANCE_COVER_SCHEMA, _CODE_FIELDS + [ExtractionField(field_key="insurer_name")])
    assert "never a phone or mobile number" in prompt
    assert "Never a contact, mobile" in prompt
    assert "formerly known as" in prompt


def test_the_policy_hypothecation_is_read() -> None:
    # Product owner 2026-10-27: an insurance hypothecation is one of the three
    # proofs of finance (with the RTO challan and a receipt from the financier).
    field = next(f for f in INSURANCE_COVER_SCHEMA.fields if f.key == "hypothecated_to")
    assert not field.required and "Cash" in field.description
    assert INSURANCE_COVER_SCHEMA.schema_version == "1.3"
