from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from verigence.di.api.v1.admin_provisioning import _effective_versions, purge_project_data
from verigence.di.repositories.database import set_tenant_context
from verigence.di.repositories.tenants import (
    provision_retention_policy,
    provision_tenant,
    provision_tenant_document_types,
)


@pytest.mark.asyncio
async def test_effective_project_masters_expose_inherited_verigence_defaults(db_session) -> None:  # type: ignore[no-untyped-def]
    tenant_id = f"uc02-defaults-{uuid.uuid4().hex[:10]}"
    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    await provision_retention_policy(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)
    await db_session.flush()

    document_types = await _effective_versions(
        db_session,
        tenant_id=tenant_id,
        master_key="DOCUMENT_TYPES",
    )
    extraction_profiles = await _effective_versions(
        db_session,
        tenant_id=tenant_id,
        master_key="EXTRACTION_PROFILES",
    )
    requirement_profiles = await _effective_versions(
        db_session,
        tenant_id=tenant_id,
        master_key="REQUIREMENT_PROFILES",
    )

    booking_type = next(item for item in document_types if item["businessKey"] == "booking_form")
    assert booking_type["status"] == "ACTIVE"
    assert booking_type["configurationSource"] == "VERIGENCE_DEFAULT"
    assert booking_type["inherited"] is True
    assert booking_type["activeForTenant"] is True

    booking_profile = next(
        item for item in extraction_profiles if item["businessKey"] == "booking_form"
    )
    assert booking_profile["status"] == "PUBLISHED"
    assert booking_profile["configurationSource"] == "VERIGENCE_DEFAULT"
    assert booking_profile["inherited"] is True

    # DI Requirement Profiles are intentionally optional. A newly provisioned
    # Project does not need a synthetic tenant profile for UC02/UC03 readiness.
    assert requirement_profiles == []


@pytest.mark.asyncio
async def test_project_purge_removes_tenant_state_but_preserves_global_defaults(db_session) -> None:  # type: ignore[no-untyped-def]
    tenant_id = f"uc02-purge-{uuid.uuid4().hex[:10]}"
    suffix = uuid.uuid4().hex[:10]
    custom_key = f"project_custom_{suffix}"
    custom_field_key = f"project_custom_field_{suffix}"
    normalization_rule_key = f"test_norm_{suffix}"
    validation_rule_key = f"test_val_{suffix}"

    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    await provision_retention_policy(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)

    custom_document_type_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO docintel.document_types (
                    document_type_id, owner_tenant_id, document_type_key,
                    display_name, category, status, created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :tenant_id, :key,
                    'Project Custom Type', 'PRINTABLE', 'DRAFT', now(), now()
                )
                RETURNING document_type_id
                """
            ),
            {"tenant_id": tenant_id, "key": custom_key},
        )
    ).scalar_one()
    custom_canonical_field_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO docintel.canonical_fields (
                    canonical_field_id, owner_tenant_id, field_key,
                    display_name, data_type, status, created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :tenant_id, :field_key,
                    'Project Custom Field', 'STRING', 'ACTIVE', now(), now()
                )
                RETURNING canonical_field_id
                """
            ),
            {"tenant_id": tenant_id, "field_key": custom_field_key},
        )
    ).scalar_one()
    custom_profile_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, created_by_actor_id,
                    created_at_utc, updated_at_utc
                ) VALUES (
                    gen_random_uuid(), :document_type_id, :tenant_id, 1,
                    'Project Custom Profile', 'DRAFT', 'test-admin', now(), now()
                )
                RETURNING profile_id
                """
            ),
            {"document_type_id": custom_document_type_id, "tenant_id": tenant_id},
        )
    ).scalar_one()
    custom_profile_field_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, aliases, score_included, score_weight,
                    use_for_subject_matching, manual_correction_allowed,
                    display_sequence, created_at_utc, updated_at_utc,
                    extraction_key, fact_role_override
                ) VALUES (
                    gen_random_uuid(), :profile_id, :canonical_field_id,
                    true, false, '[]'::jsonb, false, 0,
                    false, true, 10, now(), now(),
                    'project_custom_field', 'UNSPECIFIED'
                )
                RETURNING profile_field_id
                """
            ),
            {
                "profile_id": custom_profile_id,
                "canonical_field_id": custom_canonical_field_id,
            },
        )
    ).scalar_one()

    # Reproduce the current Schema V2 dependency shape that caused Project purge
    # to fail when extraction_profile_fields were deleted before their children.
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.normalization_rule_catalog (
                rule_key, description, implementation_key, status
            ) VALUES (:rule_key, 'Purge test normalizer', 'test.normalizer', 'ACTIVE')
            """
        ),
        {"rule_key": normalization_rule_key},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.validation_rule_catalog (
                rule_key, description, implementation_key, result_scope, status
            ) VALUES (:rule_key, 'Purge test validator', 'test.validator', 'FIELD', 'ACTIVE')
            """
        ),
        {"rule_key": validation_rule_key},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.profile_field_normalizers (
                profile_field_normalizer_id, profile_field_id,
                sequence_no, rule_key, parameters
            ) VALUES (gen_random_uuid(), :profile_field_id, 1, :rule_key, '{}'::jsonb)
            """
        ),
        {
            "profile_field_id": custom_profile_field_id,
            "rule_key": normalization_rule_key,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO docintel.profile_field_validators (
                profile_field_validator_id, profile_field_id,
                sequence_no, rule_key, parameters, severity
            ) VALUES (gen_random_uuid(), :profile_field_id, 1, :rule_key, '{}'::jsonb, 'ERROR')
            """
        ),
        {"profile_field_id": custom_profile_field_id, "rule_key": validation_rule_key},
    )
    await db_session.flush()

    global_booking_id_before = (
        await db_session.execute(
            text(
                """
                SELECT document_type_id
                FROM docintel.document_types
                WHERE owner_tenant_id IS NULL
                  AND document_type_key='booking_form'
                  AND status='ACTIVE'
                """
            )
        )
    ).scalar_one()
    global_profile_id_before = (
        await db_session.execute(
            text(
                """
                SELECT ep.profile_id
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt
                  ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key='booking_form'
                  AND ep.scope_tenant_id IS NULL
                  AND ep.status='PUBLISHED'
                LIMIT 1
                """
            )
        )
    ).scalar_one()

    result = await purge_project_data(tenant_id, None, db_session)  # type: ignore[arg-type]
    assert result.data is not None
    assert result.data.purgeStatus == "REMOVED"

    tenant_settings = (
        await db_session.execute(
            text("SELECT count(*) FROM docintel.tenant_settings WHERE tenant_id=:tid"),
            {"tid": tenant_id},
        )
    ).scalar_one()
    tenant_doc_links = (
        await db_session.execute(
            text("SELECT count(*) FROM docintel.tenant_document_types WHERE tenant_id=:tid"),
            {"tid": tenant_id},
        )
    ).scalar_one()
    custom_types = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.document_types "
                "WHERE owner_tenant_id=:tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar_one()
    custom_fields = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.canonical_fields "
                "WHERE owner_tenant_id=:tid"
            ),
            {"tid": tenant_id},
        )
    ).scalar_one()
    custom_profiles = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM docintel.extraction_profiles "
                "WHERE scope_tenant_id=:tid OR profile_id=:profile_id"
            ),
            {"tid": tenant_id, "profile_id": custom_profile_id},
        )
    ).scalar_one()
    profile_children = (
        await db_session.execute(
            text(
                """
                SELECT
                    (SELECT count(*) FROM docintel.extraction_profile_fields
                     WHERE profile_field_id=:profile_field_id) +
                    (SELECT count(*) FROM docintel.profile_field_normalizers
                     WHERE profile_field_id=:profile_field_id) +
                    (SELECT count(*) FROM docintel.profile_field_validators
                     WHERE profile_field_id=:profile_field_id)
                """
            ),
            {"profile_field_id": custom_profile_field_id},
        )
    ).scalar_one()
    assert tenant_settings == 0
    assert tenant_doc_links == 0
    assert custom_types == 0
    assert custom_fields == 0
    assert custom_profiles == 0
    assert profile_children == 0

    global_booking_id_after = (
        await db_session.execute(
            text(
                """
                SELECT document_type_id
                FROM docintel.document_types
                WHERE owner_tenant_id IS NULL
                  AND document_type_key='booking_form'
                  AND status='ACTIVE'
                """
            )
        )
    ).scalar_one()
    global_profile_id_after = (
        await db_session.execute(
            text(
                """
                SELECT ep.profile_id
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt
                  ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key='booking_form'
                  AND ep.scope_tenant_id IS NULL
                  AND ep.status='PUBLISHED'
                LIMIT 1
                """
            )
        )
    ).scalar_one()
    assert global_booking_id_after == global_booking_id_before
    assert global_profile_id_after == global_profile_id_before
