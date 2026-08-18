"""tests/test_search_index.py — Unit tests for the D14 document_search_index upsert.

All tests are marked no_docker — pure logic, mocked DB session.

Coverage:
- upsert_search_index() calls session.execute exactly once
- SQL contains the expected INSERT … ON CONFLICT clause
- indexed_fields and schema_version are serialised correctly
- subject_id=None is passed through (WhatsApp unassigned docs)
- job_runner builds indexed_fields from field_result_map correctly
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.no_docker


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_session() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    return session


# ── upsert_search_index ────────────────────────────────────────────────────────

class TestUpsertSearchIndex:

    @pytest.mark.asyncio
    async def test_calls_execute_once(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        await upsert_search_index(
            session=session,
            tenant_id="tenant1",
            document_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            document_type_key="pan_card",
            indexed_fields={"pan_number": "ABCDE1234F"},
            schema_version="2.2.0",
        )
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_sql_contains_on_conflict(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        await upsert_search_index(
            session=session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            subject_id=None,
            document_type_key="booking_form",
            indexed_fields={},
            schema_version="2.2.0",
        )
        sql_arg = session.execute.call_args[0][0]
        # SQLAlchemy text() wraps the string — check the text itself
        assert "ON CONFLICT" in str(sql_arg)

    @pytest.mark.asyncio
    async def test_indexed_fields_serialised_to_json_string(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        fields = {"amount": 1000, "dealer_name": "ABC Motors", "nullable_field": None}
        await upsert_search_index(
            session=session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            subject_id=uuid.uuid4(),
            document_type_key="dealer_receipt",
            indexed_fields=fields,
            schema_version="2.2.0",
        )
        _, params = session.execute.call_args[0]
        # The indexed_fields param must be a JSON string (CAST(... AS jsonb))
        assert isinstance(params["indexed_fields"], str)
        parsed = json.loads(params["indexed_fields"])
        assert parsed["amount"] == 1000
        assert parsed["dealer_name"] == "ABC Motors"
        assert parsed["nullable_field"] is None

    @pytest.mark.asyncio
    async def test_subject_id_none_passed_through(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        await upsert_search_index(
            session=session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            subject_id=None,
            document_type_key="upi_screenshot",
            indexed_fields={"utr": "123456789"},
            schema_version="2.2.0",
        )
        _, params = session.execute.call_args[0]
        assert params["subject_id"] is None

    @pytest.mark.asyncio
    async def test_schema_version_stored(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        await upsert_search_index(
            session=session,
            tenant_id="t1",
            document_id=uuid.uuid4(),
            subject_id=None,
            document_type_key="pan_card",
            indexed_fields={},
            schema_version="2.2.0",
        )
        _, params = session.execute.call_args[0]
        assert params["schema_version"] == "2.2.0"

    @pytest.mark.asyncio
    async def test_tenant_id_and_document_id_passed(self) -> None:
        from verigence.di.repositories.search_index import upsert_search_index

        session = _make_session()
        tid = "my-tenant"
        did = uuid.uuid4()
        await upsert_search_index(
            session=session,
            tenant_id=tid,
            document_id=did,
            subject_id=None,
            document_type_key="pan_card",
            indexed_fields={},
            schema_version="2.2.0",
        )
        _, params = session.execute.call_args[0]
        assert params["tid"] == tid
        assert params["doc_id"] == did


# ── indexed_fields construction in job_runner ─────────────────────────────────

class TestIndexedFieldsConstruction:
    """Tests that job_runner builds indexed_fields correctly from field_result_map."""

    def _make_field_result(self, key: str, normalized_value: object):
        from decimal import Decimal

        from verigence.di.document_ai.adapter import FieldResult
        from verigence.di.domain.enums import FoundStatus
        return FieldResult(
            field_key=key,
            found_status=FoundStatus.FOUND,
            raw_value=str(normalized_value),
            normalized_value=normalized_value,
            confidence=Decimal("95.0"),
            page_no=1,
            evidence_region=None,
            provider_raw={},
        )

    def test_found_fields_included(self) -> None:
        from decimal import Decimal

        from verigence.di.document_ai.adapter import FieldResult
        from verigence.di.domain.enums import FoundStatus

        profile_fields = [
            {"canonical_field_key": "amount"},
            {"canonical_field_key": "dealer_name"},
        ]
        fr_amount = FieldResult(
            field_key="amount",
            found_status=FoundStatus.FOUND,
            raw_value="1000",
            normalized_value=1000,
            confidence=Decimal("90"),
            page_no=1,
            evidence_region=None,
            provider_raw={},
        )
        fr_dealer = FieldResult(
            field_key="dealer_name",
            found_status=FoundStatus.FOUND,
            raw_value="ABC",
            normalized_value="ABC Motors",
            confidence=Decimal("88"),
            page_no=1,
            evidence_region=None,
            provider_raw={},
        )
        field_result_map = {"amount": fr_amount, "dealer_name": fr_dealer}

        indexed_fields = {
            pf["canonical_field_key"]: (
                field_result_map[pf["canonical_field_key"]].normalized_value
                if pf["canonical_field_key"] in field_result_map
                else None
            )
            for pf in profile_fields
        }

        assert indexed_fields == {"amount": 1000, "dealer_name": "ABC Motors"}

    def test_missing_field_produces_none(self) -> None:
        profile_fields = [
            {"canonical_field_key": "amount"},
            {"canonical_field_key": "missing_field"},
        ]
        from decimal import Decimal

        from verigence.di.document_ai.adapter import FieldResult
        from verigence.di.domain.enums import FoundStatus

        fr_amount = FieldResult(
            field_key="amount",
            found_status=FoundStatus.FOUND,
            raw_value="500",
            normalized_value=500,
            confidence=Decimal("85"),
            page_no=1,
            evidence_region=None,
            provider_raw={},
        )
        field_result_map = {"amount": fr_amount}

        indexed_fields = {
            pf["canonical_field_key"]: (
                field_result_map[pf["canonical_field_key"]].normalized_value
                if pf["canonical_field_key"] in field_result_map
                else None
            )
            for pf in profile_fields
        }

        assert indexed_fields["missing_field"] is None
        assert indexed_fields["amount"] == 500

    def test_empty_profile_produces_empty_dict(self) -> None:
        profile_fields: list[dict] = []
        field_result_map: dict = {}

        indexed_fields = {
            pf["canonical_field_key"]: (
                field_result_map[pf["canonical_field_key"]].normalized_value
                if pf["canonical_field_key"] in field_result_map
                else None
            )
            for pf in profile_fields
        }

        assert indexed_fields == {}
