"""domain/enums.py — All domain enumerations for Verigence DI.

These are the canonical state values used throughout the system.
They map 1:1 to the CHECK constraints in DI_POSTGRESQL_SCHEMA_v2.1.sql.
"""
from __future__ import annotations

from enum import Enum


# ── Upload lifecycle ──────────────────────────────────────────────────────────
class UploadStatus(str, Enum):
    RECEIVING = "RECEIVING"
    VALIDATING = "VALIDATING"
    FIT = "FIT"
    NOT_FIT = "NOT_FIT"
    CORRUPT = "CORRUPT"
    UPLOAD_FAILED = "UPLOAD_FAILED"


# ── Processing lifecycle ──────────────────────────────────────────────────────
class ProcessingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PROCESSING = "PROCESSING"
    RETRY_PENDING = "RETRY_PENDING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


# ── Confirmation lifecycle ────────────────────────────────────────────────────
class ConfirmationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    NOT_CONFIRMED = "NOT_CONFIRMED"


# ── Human verification ────────────────────────────────────────────────────────
class HumanVerificationStatus(str, Enum):
    """Machine-derived from confidence score vs 90.00 threshold."""
    OPTIONAL = "OPTIONAL"
    MANDATORY = "MANDATORY"


class VerificationState(str, Enum):
    """Actual completion of a human review — separate from HumanVerificationStatus."""
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"


# ── Source channels ───────────────────────────────────────────────────────────
class SourceChannel(str, Enum):
    MOBILE = "MOBILE"
    WEB = "WEB"
    API = "API"
    WHATSAPP = "WHATSAPP"


# ── Actor types ───────────────────────────────────────────────────────────────
class ActorType(str, Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    SERVICE_INTEGRATION = "SERVICE_INTEGRATION"


# ── Subject ───────────────────────────────────────────────────────────────────
class SubjectType(str, Enum):
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    OTHER = "OTHER"


class SubjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ── Content state ─────────────────────────────────────────────────────────────
class ContentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    PURGED = "PURGED"


# ── Processing jobs ───────────────────────────────────────────────────────────
class JobType(str, Enum):
    INITIAL = "INITIAL"
    EOD_RETRY = "EOD_RETRY"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ErrorClass(str, Enum):
    RETRYABLE = "RETRYABLE"
    NON_RETRYABLE = "NON_RETRYABLE"


# ── Extraction ────────────────────────────────────────────────────────────────
class FoundStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    ERROR = "ERROR"


class ValueSource(str, Enum):
    MACHINE = "MACHINE"
    HUMAN = "HUMAN"
    EXTERNAL = "EXTERNAL"


# ── Profile lifecycle ─────────────────────────────────────────────────────────
class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


# ── Document type ─────────────────────────────────────────────────────────────
class DocumentTypeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# ── Requirement classification (derived at query time, never stored) ──────────
class RequirementClassification(str, Enum):
    MANDATORY = "MANDATORY"
    OPTIONAL = "OPTIONAL"
    ADDITIONAL = "ADDITIONAL"


# ── Retention ────────────────────────────────────────────────────────────────
class RetentionDisposition(str, Enum):
    PURGE_CONTENT = "PURGE_CONTENT"
    KEEP_CONTENT = "KEEP_CONTENT"


# ── Artifact types ────────────────────────────────────────────────────────────
class ArtifactType(str, Enum):
    ORIGINAL = "ORIGINAL"
    NORMALIZED = "NORMALIZED"
    PREVIEW = "PREVIEW"
    PAGE_IMAGE = "PAGE_IMAGE"
    OCR_RAW = "OCR_RAW"
    PROVIDER_RAW = "PROVIDER_RAW"
    OTHER = "OTHER"


# ── AI adapter capabilities ───────────────────────────────────────────────────
class AICapability(str, Enum):
    CLASSIFICATION = "CLASSIFICATION"
    OCR = "OCR"
    VISION_EXTRACTION = "VISION_EXTRACTION"
    OTHER = "OTHER"
