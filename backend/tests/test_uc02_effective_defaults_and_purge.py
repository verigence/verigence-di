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
    custom_key = f"project_custom_{uuid.uuid4().hex[:10]}"

    await set_tenant_context(db_session, tenant_id)
    await provision_tenant(db_session, tenant_id)
    await provision_retention_policy(db_session, tenant_id)
    await provision_tenant_document_types(db_session, tenant_id)
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
            """
        ),
        {"tenant_id": tenant_id, "key": custom_key},
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
    assert tenant_settings == 0
    assert tenant_doc_links == 0
    assert custom_types == 0

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
