"""Tests for migration 0046 -- publishing the remaining UC03 catalog
extraction profiles.

Direct user correction (2026-09-24): "all types of schemas which are
registered in DI should be there ... its not about one or other
document." Migration 0016 registered 19 UC03 Booking/Delivery document
types with requires_processing=false, its own docstring explaining these
remain "valid manual-review evidence until an Admin publishes an
extraction profile for them." This confirms the entire remaining gap is
now closed, not just whichever type happened to get reported stuck.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_GAP_TYPE_KEYS = (
    "minimum_booking_payment_proof",
    "vehicle_rc",
    "transfer_letter",
    "authorization_letter",
    "cost_sheet",
    "value_added_service_document",
    "no_dues_certificate",
)


@pytest.mark.asyncio
async def test_every_uc03_gap_type_has_a_published_global_profile(
    db_session: AsyncSession,
) -> None:
    rows = (
        await db_session.execute(
            text(
                """
                SELECT dt.document_type_key
                FROM docintel.document_types dt
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.status = 'ACTIVE'
                  AND dt.document_type_key = ANY(:keys)
                  AND EXISTS (
                      SELECT 1 FROM docintel.extraction_profiles ep
                      WHERE ep.document_type_id = dt.document_type_id
                        AND ep.scope_tenant_id IS NULL
                        AND ep.status = 'PUBLISHED'
                  )
                """
            ),
            {"keys": list(_GAP_TYPE_KEYS)},
        )
    ).scalars().all()
    assert set(rows) == set(_GAP_TYPE_KEYS)


@pytest.mark.asyncio
async def test_every_uc03_gap_type_profile_has_at_least_one_expected_field(
    db_session: AsyncSession,
) -> None:
    # A published profile with zero fields would still pass the
    # has_published_profile check but extract nothing useful -- confirm
    # each one actually carries real field definitions.
    rows = (
        await db_session.execute(
            text(
                """
                SELECT dt.document_type_key, COUNT(epf.profile_field_id)
                FROM docintel.document_types dt
                JOIN docintel.extraction_profiles ep
                  ON ep.document_type_id = dt.document_type_id
                 AND ep.scope_tenant_id IS NULL AND ep.status = 'PUBLISHED'
                JOIN docintel.extraction_profile_fields epf
                  ON epf.profile_id = ep.profile_id AND epf.enabled = true
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key = ANY(:keys)
                GROUP BY dt.document_type_key
                """
            ),
            {"keys": list(_GAP_TYPE_KEYS)},
        )
    ).all()
    counts = dict(rows)
    for key in _GAP_TYPE_KEYS:
        assert counts.get(key, 0) > 0, f"{key} has no enabled profile fields"


@pytest.mark.asyncio
async def test_gap_types_have_requires_processing_turned_on_for_every_tenant(
    db_session: AsyncSession,
) -> None:
    still_off = (
        await db_session.execute(
            text(
                """
                SELECT dt.document_type_key, COUNT(*)
                FROM docintel.tenant_document_types tdt
                JOIN docintel.document_types dt
                  ON dt.document_type_id = tdt.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key = ANY(:keys)
                  AND tdt.requires_processing = false
                GROUP BY dt.document_type_key
                """
            ),
            {"keys": list(_GAP_TYPE_KEYS)},
        )
    ).all()
    assert still_off == [], f"still requires_processing=false for: {still_off}"
