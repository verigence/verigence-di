"""auth/permissions.py — Canonical RBAC permission catalogue (Baseline 2.2).

Source of truth: DI_RBAC_v2.2.yaml / DI_SECURITY_RBAC_v2.2.md

Rules (v2.2):
- JWT carries tenant_id, actor_id, actor_type, roles[], permissions[].
- Endpoint authorization checks permissions[], NOT role-name strings.
- Role bundles are convenience groupings; the permissions[] list is authoritative.
- The helper `has_permission(actor, perm)` is the single check point.
"""
from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    """All 27 canonical DI permissions from DI_RBAC_v2.2.yaml."""

    # Subject
    SUBJECT_CREATE          = "subject:create"
    SUBJECT_READ            = "subject:read"

    # Document
    DOCUMENT_UPLOAD         = "document:upload"
    DOCUMENT_READ           = "document:read"
    DOCUMENT_CONTENT_READ   = "document:content:read"
    DOCUMENT_FIELDS_READ    = "document:fields:read"
    DOCUMENT_QUALITY_READ   = "document:quality:read"

    # Verification
    VERIFICATION_READ       = "verification:read"
    VERIFICATION_WRITE      = "verification:write"

    # Entity links
    ENTITY_LINK_READ        = "entity_link:read"
    ENTITY_LINK_WRITE       = "entity_link:write"

    # Operations
    OPERATIONS_READ         = "operations:read"

    # Unassigned (WhatsApp)
    UNASSIGNED_DOCUMENT_READ   = "unassigned_document:read"
    UNASSIGNED_DOCUMENT_ASSIGN = "unassigned_document:assign"

    # Requirement profiles
    REQUIREMENT_PROFILE_READ    = "requirement_profile:read"
    REQUIREMENT_PROFILE_WRITE   = "requirement_profile:write"
    REQUIREMENT_PROFILE_PUBLISH = "requirement_profile:publish"
    REQUIREMENT_PROFILE_ASSIGN  = "requirement_profile:assign"

    # Extraction config
    EXTRACTION_CONFIG_READ    = "extraction_config:read"
    EXTRACTION_CONFIG_WRITE   = "extraction_config:write"
    EXTRACTION_CONFIG_PUBLISH = "extraction_config:publish"

    # Quality config
    QUALITY_CONFIG_READ  = "quality_config:read"
    QUALITY_CONFIG_WRITE = "quality_config:write"

    # Tenant config
    TENANT_CONFIG_READ  = "tenant_config:read"
    TENANT_CONFIG_WRITE = "tenant_config:write"

    # Subject matching
    SUBJECT_MATCHING_WRITE = "subject_matching:write"

    # Platform
    PLATFORM_WHATSAPP_ADMIN = "platform:whatsapp:admin"


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
