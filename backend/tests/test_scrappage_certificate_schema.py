from __future__ import annotations

import pytest

from verigence.di.document_ai.schemas import get_schema
from verigence.di.document_ai.schemas.scrappage_certificate import SCRAPPAGE_CERTIFICATE_SCHEMA

pytestmark = pytest.mark.no_docker


def test_scrappage_certificate_registry_resolves_the_dedicated_schema() -> None:
    assert get_schema("scrappage_certificate_of_deposit") is SCRAPPAGE_CERTIFICATE_SCHEMA


def test_scrappage_certificate_captures_old_vehicle_details() -> None:
    # Business ask: extract the old (scrapped) vehicle's own details, not
    # just the certificate/transfer metadata.
    keys = {field.key for field in SCRAPPAGE_CERTIFICATE_SCHEMA.fields}
    for key in (
        "old_vehicle_registration_number",
        "old_vehicle_make",
        "old_vehicle_model",
        "old_vehicle_category",
        "old_vehicle_type",
        "old_vehicle_fuel_type",
        "old_vehicle_cubic_capacity",
        "old_vehicle_seating_capacity",
        "old_vehicle_year_of_manufacturing",
        "old_vehicle_unladen_weight_kg",
        "old_vehicle_number_of_cylinders",
        "old_vehicle_gross_vehicle_weight_kg",
        "old_vehicle_wheelbase_mm",
    ):
        assert key in keys


def test_scrappage_certificate_covers_both_original_and_transfer_variants() -> None:
    by_key = {field.key: field for field in SCRAPPAGE_CERTIFICATE_SCHEMA.fields}
    variant = by_key["certificate_variant"]
    assert variant.enum == ["ORIGINAL", "TRANSFERRED"]
    # Transfer-only fields must not be required -- an ORIGINAL certificate
    # never carries them.
    for key in ("trade_date", "trade_number"):
        assert by_key[key].required is False
    # Original-only fields must not be required -- a TRANSFERRED certificate
    # never carries them.
    for key in ("scrapping_facility_name", "rvsf_registration_number", "state_of_scrapping"):
        assert by_key[key].required is False


def test_scrappage_certificate_requires_the_fields_needed_to_identify_it() -> None:
    by_key = {field.key: field for field in SCRAPPAGE_CERTIFICATE_SCHEMA.fields}
    for key in ("certificate_number", "old_vehicle_registration_number", "current_holder_name"):
        assert by_key[key].required is True
