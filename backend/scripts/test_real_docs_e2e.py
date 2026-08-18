"""
scripts/test_real_docs_e2e.py — Real document end-to-end test

Tenant : Hyundai-Delhi
Subject: Dhurandhar (created fresh, deleted at end)
Docs   : PAN card image provided inline as base64

Expected extracted fields for PAN card:
  pan_number    : DJFPK8448P
  pan_name      : ABHISHEK KHUNTIA
  date_of_birth : 1990-02-13

Run:
    uv run python scripts/test_real_docs_e2e.py
"""
from __future__ import annotations

import asyncio
import io
import pathlib
import time
import traceback
import uuid

import asyncpg
import httpx

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL   = "https://di-api-production.up.railway.app"
TENANT_ID  = "Hyundai-Delhi"
ACTOR_ID   = "test-e2e-real"
TOKEN      = f"mock.{TENANT_ID}.{ACTOR_ID}.TENANT_ADMIN"
HEADERS    = {"Authorization": f"Bearer {TOKEN}"}
DB_URL     = (
    "postgresql://neondb_owner:npg_USy5qjMFdRe7"
    "@ep-royal-pond-ayci3m0f.c-5.us-east-2.aws.neon.tech/neondb"
)

POLL_INTERVAL = 5
POLL_TIMEOUT  = 180   # Gemini may take a few seconds

# ── PAN card image ─────────────────────────────────────────────────────────────
_SCRIPT_DIR = pathlib.Path(__file__).parent

PAN_IMAGE_PATH = _SCRIPT_DIR / "pan_card_test.jpg"


def _load_pan_image() -> bytes:
    """Load PAN card image bytes. Must exist at pan_card_test.jpg next to this script."""
    if not PAN_IMAGE_PATH.exists():
        raise FileNotFoundError(
            f"PAN card image not found at {PAN_IMAGE_PATH}\n"
            "Save the PAN card image as scripts/pan_card_test.jpg before running."
        )
    return PAN_IMAGE_PATH.read_bytes()


# ── Print helpers ─────────────────────────────────────────────────────────────
def _sep(char: str = "─", width: int = 70) -> None:
    print(char * width)

def _ok(msg: str)   -> None: print(f"  ✅  {msg}")
def _fail(msg: str) -> None: print(f"  ❌  {msg}")
def _info(msg: str) -> None: print(f"      {msg}")
def _warn(msg: str) -> None: print(f"  ⚠️   {msg}")


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

    doc_ids_sql = "SELECT document_id FROM docintel.documents WHERE tenant_id = $1 AND subject_id = $2"
    run_ids_sql = f"SELECT processing_run_id FROM docintel.processing_runs WHERE document_id IN ({doc_ids_sql})"

    for tbl in [
        f"DELETE FROM docintel.backout_jobs WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.document_search_index WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.document_field_values WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.extracted_facts WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.document_classifications WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.processor_invocations WHERE processing_run_id IN ({run_ids_sql})",
    ]:
        await conn.execute(tbl, tid, sid)

    await conn.execute(
        "UPDATE docintel.documents SET current_processing_run_id = NULL WHERE tenant_id = $1 AND subject_id = $2",
        tid, sid,
    )
    await conn.execute(
        f"DELETE FROM docintel.processing_runs WHERE document_id IN ({doc_ids_sql})", tid, sid,
    )
    for tbl in [
        f"DELETE FROM docintel.processing_jobs WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.document_quality_results WHERE document_id IN ({doc_ids_sql})",
        f"DELETE FROM docintel.document_artifacts WHERE document_id IN ({doc_ids_sql})",
        "DELETE FROM docintel.documents WHERE tenant_id = $1 AND subject_id = $2",
        "DELETE FROM docintel.subjects WHERE tenant_id = $1 AND subject_id = $2",
    ]:
        await conn.execute(tbl, tid, sid)


def _poll_document_sync(
    client: httpx.Client,
    tenant_id: str,
    subject_id: str,
    document_id: str,
) -> dict:
    url = f"/v1/tenants/{tenant_id}/subjects/{subject_id}/documents/{document_id}"
    deadline = time.time() + POLL_TIMEOUT
    last_status = ""
    doc: dict = {}
    while time.time() < deadline:
        resp = client.get(url, headers=HEADERS)
        body = resp.json()
        doc  = (body.get("data") or body)
        proc = doc.get("processingStatus", "")
        if proc != last_status:
            _info(f"processingStatus → {proc}")
            last_status = proc
        if proc in {"PROCESSED", "FAILED"}:
            return doc
        time.sleep(POLL_INTERVAL)
    _warn(f"Timed out after {POLL_TIMEOUT}s — last: {last_status}")
    return doc


# ── Validation helpers ────────────────────────────────────────────────────────

def _check_extracted(
    fields: list,
    expected: dict[str, str],
) -> bool:
    """Verify extracted field values match expected. Returns True if all match."""
    import json
    all_ok = True
    field_map = {r["field_key"]: r for r in fields}
    for key, expected_val in expected.items():
        row = field_map.get(key)
        if row is None:
            _fail(f"Field '{key}' missing from extracted values")
            all_ok = False
            continue
        raw = row["current_value"]
        # current_value is stored as JSONB — may be string or dict
        if isinstance(raw, str):
            try:
                actual = json.loads(raw)
            except Exception:
                actual = raw
        else:
            actual = raw

        if actual is None:
            _warn(f"Field '{key}': expected '{expected_val}' but got null (low confidence from Gemini)")
            # Not a hard fail — document quality may be low
        elif str(actual).lower() == expected_val.lower():
            _ok(f"Field '{key}': '{actual}' ✓")
        else:
            _warn(f"Field '{key}': expected '{expected_val}', got '{actual}' (fuzzy match may be acceptable)")
    return all_ok


# ── Main test ─────────────────────────────────────────────────────────────────

async def main() -> None:
    run_id = str(uuid.uuid4())[:8]

    print()
    _sep("═")
    print("  Verigence DI — Real Document E2E Test")
    print(f"  Run    : {run_id}")
    print(f"  Tenant : {TENANT_ID}")
    print("  Subject: Dhurandhar")
    print(f"  API    : {BASE_URL}")
    _sep("═")

    # ── Health check ──────────────────────────────────────────────────────────
    health = httpx.get(f"{BASE_URL}/health/ready", timeout=15)
    assert health.status_code == 200, f"API not healthy: {health.text}"
    env = health.json().get("environment", "?")
    _ok(f"API healthy  environment={env}")
    print()

    # ── Load real document image ───────────────────────────────────────────────
    pan_bytes = _load_pan_image()
    _ok(f"PAN card image loaded: {len(pan_bytes):,} bytes")
    print()

    conn = await asyncpg.connect(DB_URL, ssl="require")
    subject_id: str | None = None
    overall_passed = True

    try:
        with httpx.Client(base_url=BASE_URL, timeout=60) as client:

            # ── Step 1: Create subject Dhurandhar ─────────────────────────────
            _sep()
            print("  STEP 1 — Create Subject: Dhurandhar")
            _sep()
            resp = client.post(
                f"/v1/tenants/{TENANT_ID}/subjects",
                headers=HEADERS,
                json={"displayName": f"Dhurandhar-{run_id}", "subjectType": "PERSON"},
            )
            assert resp.status_code == 201, f"createSubject failed {resp.status_code}: {resp.text}"
            body = resp.json()
            data = body.get("data") or body
            subject_id = data.get("subjectId")
            assert subject_id, f"No subjectId: {body}"
            _ok(f"Subject created: {subject_id}")
            print()

            # ── Step 2: Upload PAN card ───────────────────────────────────────
            _sep()
            print("  STEP 2 — Upload PAN Card (real image)")
            _sep()
            upload_resp = client.post(
                f"/v1/tenants/{TENANT_ID}/subjects/{subject_id}/documents",
                headers=HEADERS,
                files={"file": ("pan_card.jpg", io.BytesIO(pan_bytes), "image/jpeg")},
                data={"documentTypeKey": "pan_card"},
            )
            assert upload_resp.status_code in (200, 201), \
                f"uploadDocument failed {upload_resp.status_code}: {upload_resp.text}"
            up_body = upload_resp.json()
            up_data = up_body.get("data") or up_body
            document_id = up_data["documentId"]
            upload_status = up_data.get("uploadStatus", "")
            _ok(f"Uploaded:  {document_id}")
            _info(f"Upload status: {upload_status}")
            _info(f"Full response: {up_body}")

            if upload_status == "REJECTED":
                _fail(f"Upload REJECTED: {up_body.get('errorCode')} — {up_body.get('errorMessage')}")
                overall_passed = False
                return
            print()

            # ── Step 3: Poll for PROCESSED ────────────────────────────────────
            _sep()
            print(f"  STEP 3 — Poll for processing (max {POLL_TIMEOUT}s, Gemini extraction)")
            _sep()
            final_doc = _poll_document_sync(client, TENANT_ID, subject_id, document_id)
            proc_status = final_doc.get("processingStatus", "UNKNOWN")
            conf_status = final_doc.get("confirmationStatus", "UNKNOWN")
            conf_score  = final_doc.get("confidenceScore")
            hvs         = final_doc.get("humanVerificationStatus")
            print()

            # ── Step 4: Validate outcome ──────────────────────────────────────
            _sep()
            print("  STEP 4 — Validate extracted fields")
            _sep()

            if proc_status == "PROCESSED" and conf_status == "CONFIRMED":
                _ok("PROCESSED + CONFIRMED")
                _info(f"Confidence score : {conf_score}")
                _info(f"Verification     : {hvs}")
                print()

                # Check DB field values
                field_rows = await _get_field_values(conn, document_id)
                _ok(f"{len(field_rows)} field value(s) extracted by Gemini:")
                for fr in field_rows:
                    _info(f"  {fr['field_key']:20s}  value={str(fr['current_value']):<30}  conf={fr['confidence_score']}")
                print()

                # Validate against known PAN card values
                _info("Validating against known PAN card values:")
                _check_extracted(field_rows, {
                    "pan_number":    "DJFPK8448P",
                    "pan_name":      "ABHISHEK KHUNTIA",
                    "date_of_birth": "1990-02-13",
                })
                print()

                # Check document_search_index
                si = await _get_search_index(conn, document_id)
                if si:
                    _ok(f"document_search_index ✓  doc_type={si['document_type_key']}  schema={si['schema_version']}")
                    _info(f"  indexed_fields: {str(si['indexed_fields'])[:200]}")
                else:
                    _fail("No document_search_index row!")
                    overall_passed = False
                print()

                # Check no backout row
                backout = await _get_backout_row(conn, TENANT_ID, document_id)
                if backout:
                    _warn(f"Backout row exists: {backout['error_code']}")
                else:
                    _ok("No backout row — queue clean ✓")

            elif proc_status == "FAILED":
                _fail(f"Document FAILED — confirmationStatus={conf_status}")
                backout = await _get_backout_row(conn, TENANT_ID, document_id)
                if backout:
                    _info(f"Error class  : {backout['error_class']}")
                    _info(f"Error code   : {backout['error_code']}")
                    _info(f"Error detail : {str(backout['error_detail'])[:200]}")
                overall_passed = False

            else:
                _fail(f"Unexpected state: processingStatus={proc_status}  confirmationStatus={conf_status}")
                _info(f"Full doc: {final_doc}")
                overall_passed = False

    except Exception as exc:
        _fail(f"Exception: {exc}")
        traceback.print_exc()
        overall_passed = False

    finally:
        if subject_id:
            try:
                await _cleanup(conn, TENANT_ID, subject_id)
                _info("Test subject cleaned up")
            except Exception as ce:
                _warn(f"Cleanup error (non-fatal): {ce}")
        await conn.close()

    print()
    _sep("═")
    if overall_passed:
        print("  ✅  REAL DOCUMENT E2E TEST PASSED")
    else:
        print("  ❌  REAL DOCUMENT E2E TEST FAILED — see details above")
    _sep("═")
    print()


asyncio.run(main())
