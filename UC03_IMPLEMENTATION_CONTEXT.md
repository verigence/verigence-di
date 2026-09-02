# UC03 Implementation Context — DI Final-Report Contract Package 1

Repository: `verigence-di`
Branch: `fix/uc03-di-final-report-contract-v1`
Base: `dev` at `1c8f333a2455240426abbd3c7bbb72c403344077`
Mode: WRITE APPROVED for Package 1 only

## Governing rules

- UC03 stabilization only; no unrelated cleanup or redesign.
- Work one evidence-backed unit at a time.
- Do not invent document types, field keys, aliases, business rules, or source precedence.
- Preserve existing DI fact/provenance behavior and backward compatibility.
- No Audit Core, Web, or Security changes on this branch.
- No merge or deploy without separate approval.

## Approved Package 1

1. Consolidated generic invoice extraction superset using the existing one-pass invoice architecture.
2. Minimal Gate Pass extraction contract: `delivery_date`, `car_number_as_printed`, and `vehicle_registration_number` only when unambiguous.
3. Aadhaar address-component evidence fields: `address_pincode`, `address_state`, `address_district`, while preserving `aadhaar_address`.
4. Publish/activate the existing GST Certificate extraction profile and `gstin` contract.
5. One additive Alembic migration after current head `0025` for the required canonical/profile/publication changes.
6. Focused tests plus full repository CI/fresh migration verification.

## Explicitly out of scope

- Finance Type semantics.
- Bank DO / `bank_approval_letter` activation or alias.
- RTO extraction contract.
- Customer Ledger row-array contract.
- Cheque Photo, Purchase Order, Cash Ledger.
- Booking Docket Deal Type / Out-of-scope Reasons / DSA Commission.
- Accessories/EW exact monetary-field semantics.
- Trade-in monetary source semantics.
- Audit Core/Web/Security changes.

## Acceptance boundary

Implementation is not FIXED merely because source/unit tests pass. Required branch evidence before merge approval: lint, fresh PostgreSQL migration through the new revision, focused contract tests, and full pytest. Actual Gemini/document E2E remains a later verification requirement.
