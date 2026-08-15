"""
scripts/e2e.py — Generic end-to-end document test tool

Upload any file through the full pipeline and verify it reaches a terminal
state (PROCESSED+CONFIRMED or FAILED), then print extracted fields and
search-index status.

Usage:
    uv run python scripts/e2e.py <file> [options]

Examples:
    # Booking form PDF — auto-detect MIME, auto-derive doc type from filename
    uv run python scripts/e2e.py scripts/booking_form_test.pdf

    # Explicit doc type
    uv run python scripts/e2e.py scripts/pan_card_test.jpg --doc-type pan_card

    # Different tenant / subject name
    uv run python scripts/e2e.py invoice.pdf --tenant ACME --subject "Test Subject"

    # Validate specific extracted fields (key=expected)
    uv run python scripts/e2e.py scripts/pan_card_test.jpg \\
        --doc-type pan_card \\
        --expect pan_number=DJFPK8448P --expect pan_name="ABHISHEK KHUNTIA"

    # Keep the test subject in the DB after the run (skip cleanup)
    uv run python scripts/e2e.py booking_form_test.pdf --no-cleanup

    # Point at a different API (e.g. local dev)
    uv run python scripts/e2e.py booking_form_test.pdf --api http://localhost:8000

Options:
    --doc-type KEY      document_type_key to send on upload
                        (default: derived from filename stem, e.g.
                         booking_form_test.pdf → booking_form)
    --tenant ID         tenant_id  (default: Hyundai-Delhi)
    --subject NAME      subject displayName  (default: E2E-<8hex>)
    --api URL           base API URL  (default: https://di-api-production.up.railway.app)
    --timeout SECS      max seconds to wait for processing  (default: 180)
    --expect KEY=VALUE  assert extracted field equals value (repeatable)
    --no-cleanup        skip subject deletion after test
    --help / -h         show this message

MIME detection:
    .pdf  → application/pdf
    .jpg  → image/jpeg
    .jpeg → image/jpeg
    .png  → image/png
    .tif  → image/tiff
    .tiff → image/tiff
    .webp → image/webp
    .docx → application/vnd.openxmlformats-officedocument.wordprocessingml.document
    .xlsx → application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    (others) → application/octet-stream

Exit codes:
    0 — pipeline reached PROCESSED+CONFIRMED (or FAILED+backout when expected)
    1 — assertion failure, unexpected state, or connection error
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import mimetypes
import pathlib
import re
import sys
import time
import traceback
import uuid

import asyncpg
import httpx

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_API      = "https://di-api-production.up.railway.app"
_DEFAULT_TENANT   = "Hyundai-Delhi"
_DEFAULT_TIMEOUT  = 180
_POLL_INTERVAL    = 5
_DB_URL           = (
    "postgresql://neondb_owner:npg_USy5qjMFdRe7"
    "@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb"
)

# ── MIME map ──────────────────────────────────────────────────────────────────
_MIME_MAP: dict[str, str] = {
    ".pdf":  "application/pdf",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".tif":  "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_TERMINAL = {"PROCESSED", "FAILED"}


# ── Print helpers ─────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 70) -> None:
    print(char * width)

def _ok(msg: str)   -> None: print(f"  ✅  {msg}")
def _fail(msg: str) -> None: print(f"  ❌  {msg}")
def _info(msg: str) -> None: print(f"      {msg}")
def _warn(msg: str) -> None: print(f"  ⚠️   {msg}")


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="e2e.py",
        description="Generic Verigence DI end-to-end document test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )
    p.add_argument("file", help="Path to the document file to upload")
    p.add_argument(
        "--doc-type",
        dest="doc_type",
        default=None,
        help="document_type_key (default: derived from filename)",
    )
    p.add_argument("--tenant",  default=_DEFAULT_TENANT, help="Tenant ID")
    p.add_argument("--subject", default=None, help="Subject displayName")
    p.add_argument("--api",     default=_DEFAULT_API,    help="Base API URL")
    p.add_argument(
        "--timeout",
        type=int,
        default=_DEFAULT_TIMEOUT,
        help="Max seconds to wait for processing",
    )
    p.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Assert extracted field equals value (repeatable)",
    )
    p.add_argument(
        "--no-cleanup",
        dest="no_cleanup",
        action="store_true",
        help="Skip subject deletion after test",
    )
    return p.parse_args()


def _derive_doc_type(path: pathlib.Path) -> str:
    """Derive document_type_key from filename stem.

    booking_form_test.pdf → booking_form
    pan_card_test.jpg     → pan_card
    dealer_receipt.pdf    → dealer_receipt

    Strategy: strip trailing _test / _v<n> / _<8hex> suffixes, then
    take the snake_case prefix up to any trailing number/date segment.
    """
    stem = path.stem.lower()
    # Strip common suffixes: _test, _v1, _v2, _draft, _final, _<8+ hex chars>
    stem = re.sub(r"[_-](test|draft|final|v\d+|sample|demo)$", "", stem)
    stem = re.sub(r"[_-][0-9a-f]{6,}$", "", stem)
    # Strip trailing date-like suffix: _20260814
    stem = re.sub(r"[_-]\d{6,8}$", "", stem)
    return stem


def _detect_mime(path: pathlib.Path) -> str:
    ext = path.suffix.lower()
    if ext in _MIME_MAP:
        return _MIME_MAP[ext]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _parse_expects(raw: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            print(f"WARNING: --expect '{item}' has no '=' — ignored", file=sys.stderr)
            continue
        k, v = item.split("=", 1)
        result[k.strip()] = v.strip()
    return result


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _get_field_values(conn: asyncpg.Connection, document_id: str) -> list:
    return await conn.fetch(
        """
        SELECT cf.field_key, dfv.current_value, dfv.confidence_score
        FROM docintel.document_field_values dfv
        JOIN docintel.canonical_fields cf
          ON cf.canonical_field_id = dfv.canonical_field_id
        WHERE dfv.document_id = $1 AND dfv.is_current = true
        ORDER BY cf.field_key
        """,
        uuid.UUID(document_id),
    )


async def _get_search_index(conn: asyncpg.Connection, document_id: str):
    return await conn.fetchrow(
        """
        SELECT document_type_key, indexed_fields, schema_version
        FROM docintel.document_search_index
        WHERE document_id = $1
        """,
        uuid.UUID(document_id),
    )


async def _get_backout_row(conn: asyncpg.Connection, tenant_id: str, document_id: str):
    return await conn.fetchrow(
        """
        SELECT error_class, error_code, error_detail, expires_at_utc
        FROM docintel.backout_jobs
        WHERE tenant_id = $1 AND document_id = $2
        """,
        tenant_id,
        uuid.UUID(document_id),
    )


async def _cleanup(conn: asyncpg.Connection, tenant_id: str, subject_id: str) -> None:
    sid = uuid.UUID(subject_id)
    tid = tenant_id
    doc_q = "SELECT document_id FROM docintel.documents WHERE tenant_id = $1 AND subject_id = $2"
    run_q = f"SELECT processing_run_id FROM docintel.processing_runs WHERE document_id IN ({doc_q})"

    for stmt in [
        f"DELETE FROM docintel.backout_jobs             WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.document_search_index    WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.document_field_values    WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.extracted_facts          WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.document_classifications WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.processor_invocations    WHERE processing_run_id IN ({run_q})",
    ]:
        await conn.execute(stmt, tid, sid)

    await conn.execute(
        "UPDATE docintel.documents SET current_processing_run_id = NULL "
        "WHERE tenant_id = $1 AND subject_id = $2",
        tid, sid,
    )
    for stmt in [
        f"DELETE FROM docintel.processing_runs    WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.processing_jobs    WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.document_quality_results WHERE document_id IN ({doc_q})",
        f"DELETE FROM docintel.document_artifacts WHERE document_id IN ({doc_q})",
        "DELETE FROM docintel.documents WHERE tenant_id = $1 AND subject_id = $2",
        "DELETE FROM docintel.subjects  WHERE tenant_id = $1 AND subject_id = $2",
    ]:
        await conn.execute(stmt, tid, sid)


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _poll(
    client: httpx.Client,
    tenant_id: str,
    subject_id: str,
    document_id: str,
    timeout: int,
) -> dict:
    url = f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}"
    deadline = time.time() + timeout
    last_status = ""
    doc: dict = {}
    while time.time() < deadline:
        resp = client.get(url)
        body = resp.json()
        doc  = body.get("data") or body
        proc = doc.get("processingStatus", "")
        if proc != last_status:
            _info(f"processingStatus → {proc}")
            last_status = proc
        if proc in _TERMINAL:
            return doc
        time.sleep(_POLL_INTERVAL)
    _warn(f"Timed out after {timeout}s — last status: {last_status}")
    return doc


# ── Field validation ──────────────────────────────────────────────────────────

def _validate_fields(field_rows: list, expects: dict[str, str]) -> bool:
    if not expects:
        return True
    all_ok = True
    field_map = {r["field_key"]: r for r in field_rows}
    for key, expected_val in expects.items():
        row = field_map.get(key)
        if row is None:
            _fail(f"--expect: field '{key}' not found in extracted values")
            all_ok = False
            continue
        raw = row["current_value"]
        actual = json.loads(raw) if isinstance(raw, str) else raw
        if actual is None:
            _warn(f"--expect: field '{key}' = null (low-confidence extraction)")
        elif str(actual).lower() == expected_val.lower():
            _ok(f"--expect {key} = '{actual}' ✓")
        else:
            _warn(f"--expect {key}: expected '{expected_val}', got '{actual}'")
    return all_ok


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    args     = _parse_args()
    file_path = pathlib.Path(args.file)

    if not file_path.exists():
        print(f"ERROR: file not found: {file_path}", file=sys.stderr)
        return 1

    doc_type   = args.doc_type or _derive_doc_type(file_path)
    mime_type  = _detect_mime(file_path)
    file_bytes = file_path.read_bytes()
    tenant_id  = args.tenant
    run_id     = uuid.uuid4().hex[:8]
    subject_name = args.subject or f"E2E-{run_id}"
    token      = f"mock.{tenant_id}.e2e-tool.TENANT_ADMIN"
    headers    = {"Authorization": f"Bearer {token}"}
    expects    = _parse_expects(args.expect)

    _sep("═")
    print("  Verigence DI — Generic E2E Test Tool")
    _sep("═")
    _info(f"File        : {file_path}  ({len(file_bytes):,} bytes)")
    _info(f"MIME        : {mime_type}")
    _info(f"Doc type    : {doc_type}")
    _info(f"Tenant      : {tenant_id}")
    _info(f"Subject     : {subject_name}")
    _info(f"API         : {args.api}")
    _info(f"Poll timeout: {args.timeout}s")
    if expects:
        _info(f"Expects     : {expects}")
    print()

    # ── Health check ──────────────────────────────────────────────────────────
    try:
        health = httpx.get(f"{args.api}/health/ready", timeout=15)
        assert health.status_code == 200, f"HTTP {health.status_code}: {health.text}"
        env = health.json().get("environment", "?")
        _ok(f"API healthy  environment={env}")
    except Exception as exc:
        _fail(f"Health check failed: {exc}")
        return 1
    print()

    conn = await asyncpg.connect(_DB_URL, ssl="require")
    subject_id: str | None = None
    passed = True

    try:
        with httpx.Client(base_url=args.api, timeout=60, headers=headers) as client:

            # ── 1. Create subject ─────────────────────────────────────────────
            _sep()
            print("  STEP 1 — Create subject")
            _sep()
            resp = client.post(
                f"/v1/tenants/{tenant_id}/subjects",
                json={"displayName": subject_name, "subjectType": "PERSON"},
            )
            assert resp.status_code == 201, \
                f"createSubject HTTP {resp.status_code}: {resp.text}"
            body = resp.json()
            data = body.get("data") or body
            subject_id = data.get("subjectId")
            assert subject_id, f"No subjectId in response: {body}"
            _ok(f"Subject created: {subject_id}")
            print()

            # ── 2. Upload document ────────────────────────────────────────────
            _sep()
            print("  STEP 2 — Upload document")
            _sep()
            upload_resp = client.post(
                f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents",
                files={"file": (file_path.name, io.BytesIO(file_bytes), mime_type)},
                data={"documentTypeKey": doc_type},
            )
            assert upload_resp.status_code in (200, 201), \
                f"uploadDocument HTTP {upload_resp.status_code}: {upload_resp.text}"
            up_body      = upload_resp.json()
            up_data      = up_body.get("data") or up_body
            document_id  = up_data["documentId"]
            upload_status = up_data.get("uploadStatus", "")
            _ok(f"Uploaded: {document_id}  uploadStatus={upload_status}")
            _info(f"Response: {up_body}")

            if upload_status == "REJECTED":
                _fail(f"Upload REJECTED — errorCode={up_body.get('errorCode')}  "
                      f"errorMessage={up_body.get('errorMessage')}")
                passed = False
                return 1
            print()

            # ── 3. Poll ───────────────────────────────────────────────────────
            _sep()
            print(f"  STEP 3 — Poll for processing (max {args.timeout}s)")
            _sep()
            final_doc   = _poll(client, tenant_id, subject_id, document_id, args.timeout)
            proc_status = final_doc.get("processingStatus", "UNKNOWN")
            conf_status = final_doc.get("confirmationStatus", "UNKNOWN")
            conf_score  = final_doc.get("confidenceScore")
            hvs         = final_doc.get("humanVerificationStatus")
            print()

            # ── 4. Results ────────────────────────────────────────────────────
            _sep()
            print("  STEP 4 — Results")
            _sep()

            if proc_status == "PROCESSED" and conf_status == "CONFIRMED":
                _ok(f"PROCESSED + CONFIRMED  score={conf_score}  hvs={hvs}")
                print()

                # Extracted fields
                field_rows = await _get_field_values(conn, document_id)
                if field_rows:
                    _ok(f"{len(field_rows)} field(s) extracted:")
                    for fr in field_rows:
                        raw = fr["current_value"]
                        val = json.loads(raw) if isinstance(raw, str) else raw
                        _info(f"  {fr['field_key']:<30}  value={str(val):<40}  conf={fr['confidence_score']}")
                else:
                    _info("No field values in DB")
                print()

                # --expect assertions
                if expects:
                    _sep()
                    print("  STEP 5 — Field assertions")
                    _sep()
                    passed = _validate_fields(field_rows, expects) and passed
                    print()

                # document_search_index
                si = await _get_search_index(conn, document_id)
                if si:
                    _ok(f"document_search_index ✓  doc_type={si['document_type_key']}  schema={si['schema_version']}")
                    _info(f"  indexed_fields: {str(si['indexed_fields'])[:200]}")
                else:
                    _fail("No document_search_index row — Step 9c not triggered!")
                    passed = False

                # Backout queue
                backout = await _get_backout_row(conn, tenant_id, document_id)
                if backout:
                    _warn(f"Backout row present: {backout['error_code']}")
                else:
                    _ok("No backout row — queue clean ✓")

            elif proc_status == "FAILED":
                _fail(f"Document FAILED  confirmationStatus={conf_status}")
                backout = await _get_backout_row(conn, tenant_id, document_id)
                if backout:
                    _info(f"Error class  : {backout['error_class']}")
                    _info(f"Error code   : {backout['error_code']}")
                    _info(f"Error detail : {str(backout['error_detail'])[:300]}")
                else:
                    _fail("No backout row — D24 backout path not triggered!")
                passed = False

            else:
                _fail(f"Unexpected state: processingStatus={proc_status}  "
                      f"confirmationStatus={conf_status}")
                _info(f"Full doc: {final_doc}")
                passed = False

    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        passed = False

    finally:
        if subject_id and not args.no_cleanup:
            try:
                await _cleanup(conn, tenant_id, subject_id)
                _info("Test subject cleaned up ✓")
            except Exception as ce:
                _warn(f"Cleanup error (non-fatal): {ce}")
        elif subject_id and args.no_cleanup:
            _info(f"--no-cleanup: subject {subject_id} retained in DB")
        await conn.close()

    print()
    _sep("═")
    if passed:
        print("  ✅  E2E TEST PASSED")
    else:
        print("  ❌  E2E TEST FAILED — see details above")
    _sep("═")
    print()
    return 0 if passed else 1


sys.exit(asyncio.run(main()))
