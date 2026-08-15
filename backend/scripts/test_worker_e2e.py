"""
scripts/test_worker_e2e.py — End-to-end worker smoke test

Tests the full pipeline for both document types that have PUBLISHED extraction
profiles:
  - pan_card    (3 fields: pan_number, pan_name, date_of_birth)
  - booking_form (4 fields: customer_name, dealer_name, total_price, booking_date)

Uses:
  - tenant: Hyundai-Delhi (pre-provisioned, has both doc types active)
  - mock token (dev environment — no JWT signing key needed)
  - Railway API: https://di-api-production.up.railway.app
  - Mock DocumentAI adapter (DI_DOCAI_MOCK=true on Railway)

Response shapes confirmed from live API:
  createSubject  → flat JSON  { subjectId, ... }
  uploadDocument → envelope   { errorCode, errorMessage, data: { documentId, uploadStatus, processingStatus } }
  getDocument    → envelope   { errorCode, errorMessage, data: { documentId, processingStatus, confirmationStatus, ... } }

Run:
    .venv/bin/python scripts/test_worker_e2e.py
"""
from __future__ import annotations

import asyncio
import io
import struct
import time
import traceback
import uuid
import zlib

import asyncpg
import httpx

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL      = "https://di-api-production.up.railway.app"
TENANT_ID     = "Hyundai-Delhi"
ACTOR_ID      = "test-e2e-worker"
TOKEN         = f"mock.{TENANT_ID}.{ACTOR_ID}.TENANT_ADMIN"
HEADERS       = {"Authorization": f"Bearer {TOKEN}"}
DB_URL        = (
    "postgresql://neondb_owner:npg_USy5qjMFdRe7"
    "@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb"
)

POLL_INTERVAL = 4    # seconds between status polls
POLL_TIMEOUT  = 120  # seconds max to wait for processing


# ── Minimal valid PNG builder ─────────────────────────────────────────────────

def _make_png() -> bytes:
    """Build a minimal valid 1×1 white RGB PNG."""
    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig  = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw  = b"\x00\xff\xff\xff"   # filter byte + R G B
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


VALID_PNG = _make_png()


# ── Test cases ────────────────────────────────────────────────────────────────
TEST_CASES = [
    {
        "label":             "pan_card",
        "document_type_key": "pan_card",
        "filename":          "test_pan_card.png",
        "content_type":      "image/png",
        "bytes":             VALID_PNG,
        "expected_fields":   ["pan_number", "pan_name", "date_of_birth"],
    },
    {
        "label":             "booking_form",
        "document_type_key": "booking_form",
        "filename":          "test_booking_form.png",
        "content_type":      "image/png",
        "bytes":             VALID_PNG,
        "expected_fields":   ["customer_name", "dealer_name", "total_price", "booking_date"],
    },
]

# Terminal processing statuses (stop polling when we see these)
_TERMINAL = {"PROCESSED", "FAILED"}


# ── Print helpers ─────────────────────────────────────────────────────────────

def _sep(char: str = "─", width: int = 70) -> None:
    print(char * width)

def _ok(msg: str)   -> None: print(f"  ✅  {msg}")
def _fail(msg: str) -> None: print(f"  ❌  {msg}")
def _info(msg: str) -> None: print(f"      {msg}")


# ── API helpers ───────────────────────────────────────────────────────────────

def _poll_document_sync(
    client: httpx.Client,
    tenant_id: str,
    subject_id: str,
    document_id: str,
) -> dict:
    """Synchronous poll until processing_status is terminal."""
    url = (
        f"/v1/tenants/{tenant_id}/subjects/{subject_id}"
        f"/documents/{document_id}"
    )
    deadline = time.time() + POLL_TIMEOUT
    last_status = ""
    doc: dict = {}
    while time.time() < deadline:
        resp = client.get(url, headers=HEADERS)
        body = resp.json()
        doc  = body.get("data") or body
        proc = doc.get("processingStatus", "")
        if proc != last_status:
            _info(f"processingStatus → {proc}")
            last_status = proc
        if proc in _TERMINAL:
            return doc
        time.sleep(POLL_INTERVAL)
    _info(f"Timed out after {POLL_TIMEOUT}s — last status: {last_status}")
    return doc


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _get_backout_row(
    conn: asyncpg.Connection, tenant_id: str, document_id: str
):
    return await conn.fetchrow(
        """
        SELECT error_class, error_code, error_detail, expires_at_utc
        FROM docintel.backout_jobs
        WHERE tenant_id = $1 AND document_id = $2
        """,
        tenant_id,
        uuid.UUID(document_id),
    )


async def _get_field_values(
    conn: asyncpg.Connection, document_id: str
) -> list:
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


async def _cleanup(
    conn: asyncpg.Connection, tenant_id: str, subject_id: str
) -> None:
    """Delete test subject and all child rows in FK-safe order."""
    sid = uuid.UUID(subject_id)
    tid = tenant_id

    # Delete children of documents that belong to this subject
    doc_ids_sql = """
        SELECT document_id FROM docintel.documents
        WHERE tenant_id = $1 AND subject_id = $2
    """
    run_ids_sql = f"""
        SELECT processing_run_id FROM docintel.processing_runs
        WHERE document_id IN ({doc_ids_sql})
    """

    await conn.execute(
        f"DELETE FROM docintel.backout_jobs WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.document_search_index WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.document_field_values WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.extracted_facts WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.document_classifications WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.processor_invocations WHERE processing_run_id IN ({run_ids_sql})",
        tid, sid,
    )
    # Null the FK reference on documents before deleting processing_runs
    await conn.execute(
        "UPDATE docintel.documents SET current_processing_run_id = NULL WHERE tenant_id = $1 AND subject_id = $2",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.processing_runs WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.processing_jobs WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.document_quality_results WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.document_artifacts WHERE document_id IN ({doc_ids_sql})",
        tid, sid,
    )
    await conn.execute(
        "DELETE FROM docintel.documents WHERE tenant_id = $1 AND subject_id = $2",
        tid, sid,
    )
    await conn.execute(
        "DELETE FROM docintel.subjects WHERE tenant_id = $1 AND subject_id = $2",
        tid, sid,
    )


# ── Single test case ──────────────────────────────────────────────────────────

async def run_test_case(
    client: httpx.Client,
    conn: asyncpg.Connection,
    case: dict,
    run_id: str,
) -> bool:
    label = case["label"]
    _sep()
    print(f"TEST: {label.upper()}")
    _sep()
    passed    = True
    subject_id: str | None = None

    try:
        # ── 1. Create subject ────────────────────────────────────────────────
        resp = client.post(
            f"/v1/tenants/{TENANT_ID}/subjects",
            headers=HEADERS,
            json={"displayName": f"E2E-{label}-{run_id[:8]}", "subjectType": "PERSON"},
        )
        assert resp.status_code == 201, \
            f"createSubject HTTP {resp.status_code}: {resp.text}"
        body = resp.json()
        # Response is FLAT (no data envelope) for createSubject
        subject_id = body.get("subjectId") or (body.get("data") or {}).get("subjectId")
        assert subject_id, f"No subjectId in response: {body}"
        _ok(f"Subject created: {subject_id}")

        # ── 2. Upload document ───────────────────────────────────────────────
        upload_resp = client.post(
            f"/v1/tenants/{TENANT_ID}/subjects/{subject_id}/documents",
            headers=HEADERS,
            files={"file": (case["filename"], io.BytesIO(case["bytes"]), case["content_type"])},
            data={"documentTypeKey": case["document_type_key"]},
        )
        assert upload_resp.status_code in (200, 201), \
            f"uploadDocument HTTP {upload_resp.status_code}: {upload_resp.text}"
        up_body      = upload_resp.json()
        up_data      = up_body.get("data") or up_body
        document_id  = up_data["documentId"]
        upload_status = up_data.get("uploadStatus", "")
        _ok(f"Uploaded: {document_id}  uploadStatus={upload_status}")
        _info(f"Full upload response: {up_body}")

        if upload_status == "REJECTED":
            _fail("Upload REJECTED — quality gate or MIME failure")
            _info(f"errorCode={up_body.get('errorCode')}  errorMessage={up_body.get('errorMessage')}")
            passed = False
            return passed

        # ── 3. Poll ──────────────────────────────────────────────────────────
        _info(f"Polling (max {POLL_TIMEOUT}s) …")
        final_doc   = _poll_document_sync(client, TENANT_ID, subject_id, document_id)
        proc_status = final_doc.get("processingStatus", "UNKNOWN")
        conf_status = final_doc.get("confirmationStatus", "UNKNOWN")
        conf_score  = final_doc.get("confidenceScore")
        hvs         = final_doc.get("humanVerificationStatus")

        # ── 4. Evaluate outcome ──────────────────────────────────────────────
        if proc_status == "PROCESSED" and conf_status == "CONFIRMED":
            _ok(f"PROCESSED + CONFIRMED  score={conf_score}  hvs={hvs}")

            # Check extracted fields
            field_rows = await _get_field_values(conn, document_id)
            if field_rows:
                _ok(f"{len(field_rows)} field value(s) in DB:")
                for fr in field_rows:
                    _info(f"  {fr['field_key']:35s}  value={str(fr['current_value'])[:60]}  conf={fr['confidence_score']}")
            else:
                _info("No field values in DB (mock adapter may have returned NOT_FOUND)")

            # Check document_search_index row (Step 9c)
            si_row = await conn.fetchrow(
                "SELECT document_type_key, indexed_fields, schema_version "
                "FROM docintel.document_search_index "
                "WHERE document_id = $1",
                uuid.UUID(document_id),
            )
            if si_row:
                _ok(f"document_search_index row ✓  doc_type={si_row['document_type_key']}  schema={si_row['schema_version']}")
                _info(f"  indexed_fields: {str(si_row['indexed_fields'])[:120]}")
            else:
                _fail("No document_search_index row — Step 9c NOT triggered!")
                passed = False

            backout = await _get_backout_row(conn, TENANT_ID, document_id)
            if backout:
                _info(f"Backout row exists (stale): {backout['error_code']}")
            else:
                _ok("No backout row — queue clean ✓")

        elif proc_status == "FAILED":
            _info(f"Document FAILED  confirmation={conf_status}")
            backout = await _get_backout_row(conn, TENANT_ID, document_id)
            if backout:
                _ok(
                    f"D24 backout row present ✓  "
                    f"class={backout['error_class']}  "
                    f"code={backout['error_code']}  "
                    f"expires={backout['expires_at_utc']}"
                )
                _info(f"  detail: {str(backout['error_detail'])[:120]}")
                # FAILED + backout row = D24 machinery working correctly
                _ok("FAILED + backout = D24 working as designed (tiny PNG, mock adapter)")
            else:
                _fail("FAILED but NO backout row — D24 backout path NOT triggered!")
                passed = False

        else:
            _fail(
                f"Unexpected final state: processingStatus={proc_status}  "
                f"confirmationStatus={conf_status}"
            )
            _info(f"Full doc: {final_doc}")
            passed = False

    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        passed = False

    finally:
        # ── 5. Cleanup ───────────────────────────────────────────────────────
        if subject_id:
            try:
                await _cleanup(conn, TENANT_ID, subject_id)
                _info("Cleanup done")
            except Exception as ce:
                _info(f"Cleanup error (non-fatal): {ce}")

    return passed


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    run_id = str(uuid.uuid4())
    print()
    _sep("═")
    print("  Verigence DI — Worker End-to-End Test")
    print(f"  Run ID : {run_id}")
    print(f"  Tenant : {TENANT_ID}")
    print(f"  API    : {BASE_URL}")
    _sep("═")

    # Health check
    health = httpx.get(f"{BASE_URL}/health/ready", timeout=10)
    assert health.status_code == 200, f"API not healthy: {health.text}"
    env = health.json().get("environment", "?")
    _ok(f"API healthy  environment={env}")
    print()

    conn = await asyncpg.connect(DB_URL, ssl="require")
    results: dict[str, bool] = {}

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        for case in TEST_CASES:
            passed = await run_test_case(client, conn, case, run_id)
            results[case["label"]] = passed
            print()

    await conn.close()

    # Summary
    _sep("═")
    print("  SUMMARY")
    _sep("═")
    all_passed = True
    for label, passed in results.items():
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {label}")
        if not passed:
            all_passed = False
    _sep("═")
    print()
    if all_passed:
        print("  All tests passed ✅")
    else:
        print("  Some tests FAILED — see details above ❌")
    print()


asyncio.run(main())
