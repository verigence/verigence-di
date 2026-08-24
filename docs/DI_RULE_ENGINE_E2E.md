# DI + Rule Engine Live E2E Test Module

**Purpose:** prove the deployed DI flow end to end using the public HTTP contract:

```text
Create Subject
    -> Upload real document(s)
    -> DI quality/intake
    -> Document AI extraction
    -> Poll to PROCESSED
    -> Read confirmed extracted fields
    -> Assert expected extracted values
    -> POST /analyse
    -> Assert reconciliation rule findings
    -> Write JSON test evidence
```

The harness lives in `backend/e2e/di_rules`. It is deliberately separate from the normal pytest suite because a live run can invoke paid Document AI processing and needs a real deployed service/token.

## Design principles

1. **Public API only.** The harness does not read or mutate the DI database directly and does not access R2 directly.
2. **Real extraction.** It uploads the actual document bytes to the deployed DI API and waits for the deployed worker/Document AI path.
3. **Deterministic assertions.** A scenario can assert extracted fields and named reconciliation-rule outcomes.
4. **No credentials in source.** Base URL and tenant can come from environment variables; the bearer token must come from an environment variable and is never written to the JSON report.
5. **No destructive cleanup.** Processed documents are audit evidence and the current public API does not expose destructive subject cleanup. Use a dedicated E2E tenant or clearly named test subjects.
6. **Failure is strict.** Rejected upload, FAILED extraction, timeout, unconfirmed extraction (by default), field mismatch, summary mismatch, or expected-rule mismatch returns a failing exit code.

## Runtime configuration

From `backend/`:

```bash
export DI_E2E_BASE_URL="https://<di-dev-host>"
export DI_E2E_TENANT_ID="<test-tenant>"
export DI_E2E_TOKEN="<valid Security bearer token>"
```

Optional:

```bash
export DI_E2E_POLL_TIMEOUT=240
export DI_E2E_POLL_INTERVAL=4
export DI_E2E_REQUEST_TIMEOUT=60
```

The token must have the DI permissions required for subject creation, document upload/read/fields read, and `/analyse`.

## Run the committed real PAN extraction smoke

The repository already contains a real PAN image fixture. This scenario validates the real upload/extraction path and expected PAN fields; reconciliation rules are disabled because PAN alone is not an input to the current seven payment/delivery reconciliation rules.

```bash
cd backend
uv run python -m e2e.di_rules \
  --scenario e2e/scenarios/pan-extraction.json
```

Expected assertions:

- upload is `ACCEPTED`;
- processing reaches `PROCESSED`;
- extraction is `CONFIRMED`;
- `pan_number`, `pan_name`, and `date_of_birth` match the committed fixture expectations.

## Run a full reconciliation scenario

Copy `backend/e2e/scenarios/reconciliation.template.json` to a new scenario file and point it at real test documents. A useful full scenario normally includes:

- `booking_form` or `booking_docket`;
- one or more `dealer_receipt` documents;
- `bank_statement` or `bank_statement_extract`;
- `delivery_order` or `delivery_order_cover`.

Then run:

```bash
cd backend
uv run python -m e2e.di_rules \
  --scenario e2e/scenarios/my-reconciliation.json
```

The harness uploads every document under the **same Subject**, waits for each extraction, reads its extracted fields, then submits all resulting `documentId` values to:

```text
POST /v1/tenants/{tenantId}/analyse
```

## Scenario format

```json
{
  "name": "my-reconciliation",
  "subject": {
    "displayName": "TEST CUSTOMER NAME",
    "subjectType": "PERSON"
  },
  "requireConfirmed": true,
  "numericTolerance": 1.0,
  "documents": [
    {
      "name": "booking",
      "documentTypeKey": "booking_form",
      "path": "../fixtures/booking.pdf",
      "expectFields": {
        "total_price": 500000
      }
    }
  ],
  "rules": {
    "enabled": true,
    "expectedSummary": "RECONCILED",
    "expect": {
      "R1_AMOUNT_MATCH": "PASS"
    }
  }
}
```

Document paths are relative to the scenario JSON file.

`expectFields` is optional. Text comparison is case-insensitive and collapses repeated whitespace. Numeric comparison accepts formatted strings such as `1,250.00` and uses `numericTolerance`.

`rules.expect` can contain only the rules important to a scenario; unlisted findings are still printed and preserved in the JSON report but are not asserted.

## Current reconciliation rules

The deployed DI reconciliation engine currently evaluates:

| Rule | Verification |
| --- | --- |
| `R1_AMOUNT_MATCH` | Dealer receipt amount total matches booking total |
| `R2_UTR_SUFFIX_MATCH` | Receipt RTGS/reference matches the suffix of bank-statement UTR |
| `R3_DATE_PROXIMITY` | Receipt/payment date is within 3 days of bank transaction date |
| `R4_NAME_MATCH` | Receipt payer/payee/customer name fuzzy-matches Subject display name at >=80% |
| `R5_TOTAL_CHECK` | Receipt total matches booking total within the rule tolerance |
| `R6_DATE_SEQUENCE` | Delivery date is not before the latest receipt date |
| `R7_DUPLICATE_DETECTION` | No duplicate receipt shares amount + date + RTGS/reference |

The engine summary is:

- `RECONCILED` — every applicable rule passed;
- `DISCREPANCY` — at least one applicable rule failed;
- `INSUFFICIENT_DATA` — all rules were skipped because required extracted fields/documents were unavailable.

## Evidence report

Every run writes a JSON report by default to:

```text
backend/e2e/results/<scenario>-<utc-timestamp>.json
```

The report contains:

- deployed base URL and tenant;
- created Subject ID;
- each uploaded Document ID;
- processing/confirmation status;
- extracted field values and confidence scores;
- complete `/analyse` result and rule detail;
- final PASS/FAIL and failure reasons.

It never writes the bearer token.

Use `--report <path>` to choose another evidence location.

## What this harness intentionally does not do

- It does not use `MockDocumentAIAdapter`.
- It does not invoke the worker directly inside the test process.
- It does not query `docintel.*` tables to decide whether the test passed.
- It does not silently correct extracted values through the human-verification endpoint.
- It does not turn a `FAILED`, `PENDING`, `SKIPPED`, or missing result into a pass unless the scenario explicitly expects that rule result.

This makes the result a true service-level E2E check of the same boundaries used by the product.
