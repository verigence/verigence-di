"""auth/permissions.py — Canonical RBAC permission catalogue.

Permission strings use canonical dot-separated, module-prefixed format.
Security module owns the permission catalogue and issues these strings in
the Verigence Access Token permissions[] claim.
DI checks permissions[] — never role-name strings.
"""
from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    """All 28 canonical DI permissions — module-prefixed dot-separated format."""

    # Subject
    SUBJECT_CREATE          = "di.subject.create"
    SUBJECT_READ            = "di.subject.read"

    # Document
    DOCUMENT_UPLOAD         = "di.document.upload"
    DOCUMENT_READ           = "di.document.read"
    DOCUMENT_CONTENT_READ   = "di.document.content.read"
    DOCUMENT_FIELDS_READ    = "di.document.fields.read"
    DOCUMENT_QUALITY_READ   = "di.document.quality.read"
    DOCUMENT_DELETE         = "di.document.delete"

    # Verification
    VERIFICATION_READ       = "di.verification.read"
    VERIFICATION_WRITE      = "di.verification.write"

    # Entity links
    ENTITY_LINK_READ        = "di.entity_link.read"
    ENTITY_LINK_WRITE       = "di.entity_link.write"

    # Operations
    OPERATIONS_READ         = "di.operations.read"

    # Unassigned (WhatsApp)
    UNASSIGNED_DOCUMENT_READ   = "di.unassigned_document.read"
    UNASSIGNED_DOCUMENT_ASSIGN = "di.unassigned_document.assign"

    # Requirement profiles
    REQUIREMENT_PROFILE_READ    = "di.requirement_profile.read"
    REQUIREMENT_PROFILE_WRITE   = "di.requirement_profile.write"
    REQUIREMENT_PROFILE_PUBLISH = "di.requirement_profile.publish"
    REQUIREMENT_PROFILE_ASSIGN  = "di.requirement_profile.assign"

    # Extraction config
    EXTRACTION_CONFIG_READ    = "di.extraction_config.read"
    EXTRACTION_CONFIG_WRITE   = "di.extraction_config.write"
    EXTRACTION_CONFIG_PUBLISH = "di.extraction_config.publish"

    # Quality config
    QUALITY_CONFIG_READ  = "di.quality_config.read"
    QUALITY_CONFIG_WRITE = "di.quality_config.write"

    # Tenant config
    TENANT_CONFIG_READ  = "di.tenant_config.read"
    TENANT_CONFIG_WRITE = "di.tenant_config.write"

    # Subject matching
    SUBJECT_MATCHING_WRITE = "di.subject_matching.write"

    # Platform
    PLATFORM_WHATSAPP_ADMIN = "di.platform.whatsapp.admin"


# ── Role-to-permissions bundles (v2.2) ────────────────────────────────────────
# These are the default bundles. The JWT permissions[] is authoritative at runtime.

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "DOCUMENT_OPERATOR": frozenset({
        Permission.SUBJECT_CREATE,
        Permission.SUBJECT_READ,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CONTENT_READ,
        Permission.DOCUMENT_FIELDS_READ,
        Permission.DOCUMENT_QUALITY_READ,
        Permission.ENTITY_LINK_READ,
        Permission.ENTITY_LINK_WRITE,
    }),
    "DOCUMENT_VERIFIER": frozenset({
        Permission.SUBJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CONTENT_READ,
        Permission.DOCUMENT_FIELDS_READ,
        Permission.DOCUMENT_QUALITY_READ,
        Permission.VERIFICATION_READ,
        Permission.VERIFICATION_WRITE,
    }),
    "OPERATIONS_VIEWER": frozenset({
        Permission.SUBJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.VERIFICATION_READ,
        Permission.OPERATIONS_READ,
    }),
    "UNASSIGNED_INTAKE_OPERATOR": frozenset({
        Permission.SUBJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_CONTENT_READ,
        Permission.DOCUMENT_FIELDS_READ,
        Permission.DOCUMENT_QUALITY_READ,
        Permission.UNASSIGNED_DOCUMENT_READ,
        Permission.UNASSIGNED_DOCUMENT_ASSIGN,
    }),
    "CONFIGURATION_ADMIN": frozenset({
        Permission.REQUIREMENT_PROFILE_READ,
        Permission.REQUIREMENT_PROFILE_WRITE,
        Permission.REQUIREMENT_PROFILE_PUBLISH,
        Permission.REQUIREMENT_PROFILE_ASSIGN,
        Permission.EXTRACTION_CONFIG_READ,
        Permission.EXTRACTION_CONFIG_WRITE,
        Permission.EXTRACTION_CONFIG_PUBLISH,
        Permission.QUALITY_CONFIG_READ,
        Permission.QUALITY_CONFIG_WRITE,
        Permission.TENANT_CONFIG_READ,
    }),
    "TENANT_ADMIN": frozenset({
        Permission.DOCUMENT_CONTENT_READ,
        Permission.DOCUMENT_DELETE,
        Permission.DOCUMENT_FIELDS_READ,
        Permission.DOCUMENT_QUALITY_READ,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_UPLOAD,
        Permission.ENTITY_LINK_READ,
        Permission.ENTITY_LINK_WRITE,
        Permission.EXTRACTION_CONFIG_PUBLISH,
        Permission.EXTRACTION_CONFIG_READ,
        Permission.EXTRACTION_CONFIG_WRITE,
        Permission.OPERATIONS_READ,
        Permission.QUALITY_CONFIG_READ,
        Permission.QUALITY_CONFIG_WRITE,
        Permission.REQUIREMENT_PROFILE_ASSIGN,
        Permission.REQUIREMENT_PROFILE_PUBLISH,
        Permission.REQUIREMENT_PROFILE_READ,
        Permission.REQUIREMENT_PROFILE_WRITE,
        Permission.SUBJECT_CREATE,
        Permission.SUBJECT_READ,
        Permission.SUBJECT_MATCHING_WRITE,
        Permission.TENANT_CONFIG_READ,
        Permission.TENANT_CONFIG_WRITE,
        Permission.UNASSIGNED_DOCUMENT_ASSIGN,
        Permission.UNASSIGNED_DOCUMENT_READ,
        Permission.VERIFICATION_READ,
        Permission.VERIFICATION_WRITE,
    }),
    "SERVICE_INTEGRATION": frozenset({
        Permission.SUBJECT_CREATE,
        Permission.SUBJECT_READ,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_FIELDS_READ,
        Permission.ENTITY_LINK_READ,
        Permission.ENTITY_LINK_WRITE,
    }),
    "PLATFORM_ADMIN": frozenset({
        Permission.PLATFORM_WHATSAPP_ADMIN,
    }),
}
