"""Logging pipeline and error-contract regressions (observability hardening)."""
from __future__ import annotations

import io
import json
import logging
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import structlog
from fastapi import HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient

from verigence.di import logging_config, main
from verigence.di.api.v1 import configuration_proposals, documents
from verigence.di.api.v1.schemas import ApiResponse, UploadData
from verigence.di.application import intake
from verigence.di.application.intake import IntakeError, intake_document
from verigence.di.auth import jwks, verifier
from verigence.di.auth.principal import ActorPrincipal
from verigence.di.domain.enums import ActorType, UploadStatus
from verigence.di.errors import ErrorCode, ProblemException
from verigence.di.main import CORRELATION_ID_HEADER, PROBLEM_MEDIA_TYPE, create_app
from verigence.di.settings import get_settings

# conftest's session-scoped _patch_jwks_cache replaces JWKSCache.get_key for the rest of the run
# once any smoke test uses it; these tests exercise the real method, captured at import.
_REAL_GET_KEY = jwks.JWKSCache.get_key


@pytest.fixture
def real_jwks_get_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jwks.JWKSCache, "get_key", _REAL_GET_KEY)

pytestmark = pytest.mark.no_docker

# {"alg":"RS256","kid":"kid-1"} . {} . signature — parses as a JWT header only.
_JWT_WITH_KID = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtpZC0xIn0.e30.c2ln"


class _RecordingLogger:
    """Stand-in for a module structlog logger that records (level, event, fields)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def _record(self, level: str) -> Any:  # noqa: ANN401
        def _log(event: str, **fields: Any) -> None:
            self.events.append((level, event, fields))

        return _log

    def __getattr__(self, level: str) -> Any:  # noqa: ANN401
        return self._record(level)


@pytest.fixture
def json_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DI_LOG_FORMAT", "json")
    monkeypatch.setenv("VERIGENCE_GIT_SHA", "0123456789abcdef0123")
    get_settings.cache_clear()
    logging_config.configure_logging(process="api")
    yield
    get_settings.cache_clear()
    structlog.contextvars.clear_contextvars()


def _format_with_root_handler(record: logging.LogRecord) -> dict[str, Any]:
    formatter = logging.getLogger().handlers[0].formatter
    assert formatter is not None
    rendered: dict[str, Any] = json.loads(formatter.format(record))
    return rendered


# ── 1. Logging pipeline ───────────────────────────────────────────────────────

def test_json_renderer_everywhere_except_local() -> None:
    assert logging_config.use_console_renderer("local", "") is True
    assert logging_config.use_console_renderer("dev", "") is False
    assert logging_config.use_console_renderer("production", None) is False
    assert logging_config.use_console_renderer("dev", "console") is True
    assert logging_config.use_console_renderer("local", "JSON") is False


def test_stdlib_record_is_structured_and_sanitised(json_logging: None) -> None:
    structlog.contextvars.bind_contextvars(correlation_id="corr-stdlib-1")
    try:
        raise ValueError("secret-exception-message")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="verigence.di.auth.verifier",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="jwks %s",
        args=("refresh",),
        exc_info=exc_info,
    )
    record.__dict__.update({"error": "secret-extra-value", "key_count": 3})

    event = _format_with_root_handler(record)

    assert event["event"] == "jwks refresh"
    assert event["level"] == "warning"
    assert event["logger"] == "verigence.di.auth.verifier"
    assert event["correlation_id"] == "corr-stdlib-1"
    assert event["key_count"] == 3
    assert "timestamp" in event
    assert event["service"] == "verigence-di"
    assert event["environment"] == get_settings().env.value
    assert event["version"] == "0123456789ab"
    assert event["process"] == "api"
    assert event["exception_type"] == "ValueError"
    assert "error" not in event
    rendered = json.dumps(event)
    assert "secret-extra-value" not in rendered
    assert "secret-exception-message" not in rendered
    assert "Traceback" not in rendered


def test_no_correlation_id_is_invented_outside_a_request(json_logging: None) -> None:
    structlog.contextvars.clear_contextvars()
    record = logging.LogRecord("alembic", logging.ERROR, __file__, 1, "failed", None, None)
    assert "correlation_id" not in _format_with_root_handler(record)


def test_uvicorn_is_routed_through_root_and_probe_access_lines_dropped(
    json_logging: None,
) -> None:
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        assert logging.getLogger(name).handlers == []
        assert logging.getLogger(name).propagate is True
    for name in ("httpx", "httpcore", "botocore", "boto3", "urllib3"):
        assert logging.getLogger(name).level == logging.WARNING

    access = logging.getLogger("uvicorn.access")

    def _access(path: str) -> logging.LogRecord:
        return logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("1.2.3.4:1", "GET", path, "1.1", 200),
            None,
        )

    assert not access.filter(_access("/health/live"))
    assert not access.filter(_access("/health"))
    assert not access.filter(_access("/ready"))
    assert access.filter(_access("/v1/tenants/t/subjects"))


@pytest.mark.asyncio
async def test_http_request_log_skips_health_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    recorder = _RecordingLogger()
    monkeypatch.setattr(main, "logger", recorder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/health/live")
        await client.get("/__missing_route")
    paths = [fields.get("path") for _, event, fields in recorder.events if event == "http_request"]
    assert paths == ["/__missing_route"]


# ── 2. Error responses ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_http_exception_string_detail_headers_media_type_and_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()

    @app.get("/__test_missing_resource")
    async def _missing() -> None:
        raise HTTPException(status_code=404, detail="No indexed documents found")

    @app.get("/__test_challenge")
    async def _challenge() -> None:
        raise HTTPException(status_code=401, detail="Token required", headers={"WWW-Authenticate": "Bearer"})

    @app.get("/__test_dependency")
    async def _dependency() -> None:
        raise HTTPException(status_code=503, detail="Downstream unavailable")

    recorder = _RecordingLogger()
    monkeypatch.setattr(main, "logger", recorder)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/__test_missing_resource")
        challenge = await client.get("/__test_challenge")
        dependency = await client.get("/__test_dependency")
        route_missing = await client.get("/__no_such_route")

    assert missing.status_code == 404
    assert missing.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = missing.json()
    assert body["code"] == ErrorCode.RESOURCE_NOT_FOUND.code
    assert body["detail"] == "No indexed documents found"
    assert body["errorCategory"] == "BUSINESS"
    assert body["correlationId"] == missing.headers[CORRELATION_ID_HEADER]

    assert challenge.status_code == 401
    assert challenge.headers["www-authenticate"] == "Bearer"
    assert challenge.json()["errorCategory"] == "SECURITY"

    assert dependency.json()["code"] == ErrorCode.DEPENDENCY_UNAVAILABLE.code
    assert dependency.json()["retryable"] is True

    assert route_missing.json()["code"] == ErrorCode.ROUTE_NOT_FOUND.code

    levels = {
        fields["http_status"]: (level, event)
        for level, event, fields in recorder.events
        if "http_status" in fields and event != "http_request"
    }
    assert levels[404] == ("info", "di_business_error")
    assert levels[401] == ("warning", "di_security_rejection")
    assert levels[503] == ("error", "di_technical_error")


@pytest.mark.asyncio
async def test_problem_exception_renders_canonical_body() -> None:
    app = create_app()

    @app.get("/__test_problem")
    async def _problem() -> None:
        raise IntakeError(ErrorCode.SUBJECT_NOT_FOUND, "Subject does not exist in this Tenant.")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/__test_problem", headers={CORRELATION_ID_HEADER: "corr-problem"})

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["code"] == "SUBJECT_NOT_FOUND"
    assert body["retryable"] is False
    assert body["errorCategory"] == "BUSINESS"
    assert body["type"].endswith("subject_not_found")
    assert body["correlationId"] == "corr-problem"


def test_error_categories_cover_business_and_technical_classes() -> None:
    assert ErrorCode.VALIDATION_ERROR.error_category == "VALIDATION"
    assert ErrorCode.FILE_TOO_LARGE.error_category == "VALIDATION"
    assert ErrorCode.SUBJECT_NOT_FOUND.error_category == "BUSINESS"
    assert ErrorCode.RETENTION_POLICY_NOT_CONFIGURED.error_category == "BUSINESS"
    assert ErrorCode.UNAUTHORIZED.error_category == "SECURITY"
    assert ErrorCode.FORBIDDEN.error_category == "SECURITY"
    assert ErrorCode.STORAGE_WRITE_FAILED.error_category == "DEPENDENCY"
    assert ErrorCode.SECURITY_INTEGRATION_FAILED.error_category == "DEPENDENCY"
    assert ErrorCode.INTERNAL_ERROR.error_category == "TECHNICAL"


# ── 3/5. Intake typed errors ──────────────────────────────────────────────────

def _upload() -> UploadFile:
    return UploadFile(filename="a.pdf", file=io.BytesIO(b"%PDF-1.4 test"))


@pytest.mark.asyncio
async def test_intake_invalid_requirement_ref_is_validation_error() -> None:
    with pytest.raises(IntakeError) as caught:
        await intake_document(
            session=AsyncMock(),
            storage=MagicMock(),
            tenant_id="t1",
            subject_id=uuid.uuid4(),
            uploaded_by_actor_id="a1",
            uploaded_by_actor_type="USER",
            correlation_id="c1",
            upload=_upload(),
            audit_requirement_ref="x" * 161,
            audit_storage_context={},
        )
    assert caught.value.error is ErrorCode.VALIDATION_ERROR
    assert caught.value.error.http_status == 422


@pytest.mark.asyncio
async def test_intake_missing_retention_policy_is_409(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake, "get_active_retention_policy", AsyncMock(return_value=None))
    with pytest.raises(IntakeError) as caught:
        await intake_document(
            session=AsyncMock(),
            storage=MagicMock(),
            tenant_id="t1",
            subject_id=uuid.uuid4(),
            uploaded_by_actor_id="a1",
            uploaded_by_actor_type="USER",
            correlation_id="c1",
            upload=_upload(),
        )
    assert caught.value.error is ErrorCode.RETENTION_POLICY_NOT_CONFIGURED
    assert caught.value.error.http_status == 409
    assert caught.value.error.retryable is False


def _intake_session(subject_row: object) -> AsyncMock:
    subject_result = MagicMock()
    subject_result.one_or_none.return_value = subject_row
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[subject_result] + [MagicMock()] * 10)
    return session


def _retention() -> dict[str, object]:
    return {
        "retention_policy_id": uuid.uuid4(),
        "retention_days": 365,
        "disposition": "PURGE_CONTENT",
    }


@pytest.mark.asyncio
async def test_intake_unknown_subject_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake, "get_active_retention_policy", AsyncMock(return_value=_retention()))
    with pytest.raises(IntakeError) as caught:
        await intake_document(
            session=_intake_session(None),
            storage=MagicMock(),
            tenant_id="t1",
            subject_id=uuid.uuid4(),
            uploaded_by_actor_id="a1",
            uploaded_by_actor_type="USER",
            correlation_id="c1",
            upload=_upload(),
        )
    assert caught.value.error is ErrorCode.SUBJECT_NOT_FOUND
    assert caught.value.error.http_status == 404


@pytest.mark.asyncio
async def test_intake_storage_outage_is_retryable_503_not_business_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(intake, "get_active_retention_policy", AsyncMock(return_value=_retention()))
    monkeypatch.setattr(
        intake,
        "create_document_receiving",
        AsyncMock(return_value={"document_id": uuid.uuid4()}),
    )
    persisted = AsyncMock()
    monkeypatch.setattr(intake, "update_document_upload_complete", persisted)
    storage = MagicMock()
    storage.put_stream = AsyncMock(side_effect=OSError("bucket-secret-detail"))
    subject_row = MagicMock()
    subject_row.__getitem__ = MagicMock(return_value="Subject")

    with pytest.raises(IntakeError) as caught:
        await intake_document(
            session=_intake_session(subject_row),
            storage=storage,
            tenant_id="t1",
            subject_id=uuid.uuid4(),
            uploaded_by_actor_id="a1",
            uploaded_by_actor_type="USER",
            correlation_id="c1",
            upload=_upload(),
        )

    assert caught.value.error is ErrorCode.STORAGE_WRITE_FAILED
    assert caught.value.error.http_status == 503
    assert caught.value.error.retryable is True
    assert persisted.await_args is not None
    kwargs = persisted.await_args.kwargs
    assert kwargs["upload_status"] == UploadStatus.UPLOAD_FAILED
    assert "bucket-secret-detail" not in kwargs["upload_issue_detail"]


# ── 4. No raw exception text from configuration authoring ────────────────────

async def _create_proposal(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> dict[str, Any]:
    monkeypatch.setattr(configuration_proposals, "_canonical_catalogue", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        configuration_proposals,
        "generate_schema_proposal",
        AsyncMock(side_effect=failure),
    )
    storage = MagicMock()
    storage.put_stream = AsyncMock()
    actor = ActorPrincipal(
        actor_id="admin-1",
        tenant_id="t1",
        actor_type=ActorType.USER,
        roles=frozenset(),
        permissions=frozenset(),
        raw_claims={},
    )
    with pytest.raises(HTTPException) as caught:
        await configuration_proposals.create_configuration_proposal(
            tenant_id="t1",
            file=UploadFile(filename="s.pdf", file=io.BytesIO(b"%PDF-1.4 sample")),
            display_name=None,
            description=None,
            actor=actor,
            storage=storage,
        )
    detail = caught.value.detail
    assert isinstance(detail, dict)
    assert caught.value.status_code == detail["status"]
    return detail


@pytest.mark.asyncio
async def test_gemini_failure_does_not_echo_exception_text(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = await _create_proposal(monkeypatch, RuntimeError("gemini-secret-response"))
    assert detail["code"] == ErrorCode.INTERNAL_ERROR.code
    assert "gemini-secret-response" not in json.dumps(detail)
    assert "RuntimeError" not in json.dumps(detail)


@pytest.mark.asyncio
async def test_gemini_invalid_output_is_dependency_502(monkeypatch: pytest.MonkeyPatch) -> None:
    detail = await _create_proposal(monkeypatch, ValueError("Duplicate fieldKey: secret_key"))
    assert detail["code"] == ErrorCode.DOCUMENT_AI_RESPONSE_INVALID.code
    assert detail["status"] == 502
    assert detail["retryable"] is True
    assert detail["errorCategory"] == "DEPENDENCY"
    assert "secret_key" not in json.dumps(detail)


# ── 5. Token verification: invalid → 401, JWKS outage → 503 ──────────────────

def _failing_jwks(monkeypatch: pytest.MonkeyPatch) -> jwks.JWKSCache:
    def _raise(*args: object, **kwargs: object) -> None:
        raise httpx.ConnectError("jwks host unreachable")

    monkeypatch.setattr(jwks.httpx, "get", _raise)
    return jwks.JWKSCache("https://security.invalid/.well-known/jwks.json")


@pytest.mark.asyncio
async def test_invalid_token_is_401_with_challenge() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/tenants/t1/subjects",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    body = response.json()
    assert body["code"] == ErrorCode.UNAUTHORIZED.code
    assert body["detail"] == "Invalid or expired token"
    assert body["errorCategory"] == "SECURITY"
    assert "type" in body and "category" in body


@pytest.mark.asyncio
@pytest.mark.usefixtures("real_jwks_get_key")
async def test_jwks_outage_is_503_not_401(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _failing_jwks(monkeypatch)
    monkeypatch.setattr(verifier, "get_jwks_cache", lambda: cache)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/tenants/t1/subjects",
            headers={"Authorization": f"Bearer {_JWT_WITH_KID}"},
        )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == ErrorCode.SECURITY_INTEGRATION_FAILED.code
    assert body["retryable"] is True
    assert body["errorCategory"] == "DEPENDENCY"


@pytest.mark.usefixtures("real_jwks_get_key")
def test_jwks_outage_keeps_serving_cached_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = _failing_jwks(monkeypatch)
    cached_key = object()
    cache._keys = {"kid-1": cached_key}
    cache._fetched_at = 0.0  # stale → forces a (failing) refresh
    assert cache.get_key("kid-1") is cached_key
    with pytest.raises(jwks.JWKSUnavailableError):
        cache.get_key("kid-unknown")


@pytest.mark.usefixtures("real_jwks_get_key")
def test_jwks_fetch_propagates_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def _get(url: str, *, timeout: float, headers: dict[str, str]) -> Any:  # noqa: ANN401
        del url, timeout
        seen.update(headers)
        response = MagicMock()
        response.json.return_value = {"keys": []}
        return response

    monkeypatch.setattr(jwks.httpx, "get", _get)
    structlog.contextvars.bind_contextvars(correlation_id="corr-jwks-1")
    try:
        assert jwks.JWKSCache("https://security.invalid/jwks").get_key("kid-1") is None
    finally:
        structlog.contextvars.clear_contextvars()
    assert seen == {"X-Correlation-ID": "corr-jwks-1"}


# ── D8 business rejection envelopes carry the correlation id ─────────────────

def test_d8_envelope_includes_correlation_id_only_when_set() -> None:
    success = ApiResponse[UploadData](errorCode="000", errorMessage="Success")
    assert "correlationId" not in success.model_dump()
    rejected = ApiResponse[UploadData](errorCode="E001", errorMessage="Rejected", correlationId="c-1")
    assert rejected.model_dump()["correlationId"] == "c-1"


@pytest.mark.asyncio
async def test_rejected_upload_envelope_has_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _session(tenant_id: str) -> AsyncIterator[object]:
        del tenant_id
        yield object()

    document_id = uuid.uuid4()
    monkeypatch.setattr(documents, "tenant_session", _session)
    monkeypatch.setattr(documents, "subject_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(documents, "get_storage_adapter", lambda: MagicMock())
    monkeypatch.setattr(
        documents,
        "intake_document",
        AsyncMock(
            return_value={
                "document_id": document_id,
                "upload_status": UploadStatus.NOT_FIT,
                "upload_issue_code": "BLUR",
            }
        ),
    )
    actor = ActorPrincipal(
        actor_id="a1",
        tenant_id="t1",
        actor_type=ActorType.USER,
        roles=frozenset(),
        permissions=frozenset(),
        raw_claims={},
    )
    structlog.contextvars.bind_contextvars(correlation_id="corr-d8-1")
    try:
        response = await documents.upload_subject_document(
            tenantId="t1",
            subjectId=uuid.uuid4(),
            actor=actor,
            file=_upload(),
            documentTypeKey=None,
        )
    finally:
        structlog.contextvars.clear_contextvars()
    assert response.errorCode == "E001"
    assert response.model_dump()["correlationId"] == "corr-d8-1"


def test_problem_exception_detail_defaults_to_title() -> None:
    exc = ProblemException(ErrorCode.CONFLICT)
    assert exc.detail == ErrorCode.CONFLICT.title
