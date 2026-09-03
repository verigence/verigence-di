# UC03 Implementation Context — DI Booking Docket Final-Report Contract Package 2

Repository: `verigence-di`
Branch: `fix/uc03-di-booking-docket-final-report-v1`
Base: `dev` at `a7089fe1604df7f5cf9e6b33ee5f2f98f537ac72`
Mode: Package-2 continuation authorized by the user on 2026-09-03; do not pause for routine write/merge steps while this exact scope remains green and contained.

## Governing rules

- UC03 stabilization only; no unrelated cleanup or redesign.
- Work one evidence-backed unit at a time.
- Preserve existing DI fact/provenance behavior and backward compatibility.
- Existing `booking_docket` identity is authoritative for the UC03 Booking requirement.
- Runtime is database-profile driven; do not redesign classifier or extraction orchestration.
- No Audit Core, Web, or Security changes on this branch.
- Merge to `dev` uses the repository's normal CI/deployment behavior.
- Stop if implementation requires scope outside this Package 2 contract.

## Package 2 scope

Publish one new immutable global `booking_docket` extraction-profile version by cloning the currently published profile and adding only these final-report evidence fields:

1. `deal_type` — STRING — exact deal type/category only when explicitly printed, written, selected or marked.
2. `out_of_scope_reasons` — STRING — exact out-of-scope reason text when explicitly present; preserve multiple printed reasons as source text rather than inventing a derived structure.
3. `dsa_commission_amount` — CURRENCY — DSA commission monetary value only when explicitly shown.
4. `exchange_applicable` — BOOLEAN — true/false only from an explicit Yes/No, checkbox, tick or equivalent selection; never infer from exchange value or other deal data.

Use additive migration `0027` after current head `0026`. Retire the previous published `booking_docket` profile only when the new cloned profile is ready to publish. Preserve prior profile fields/rules and historical extracted facts.

## Explicitly out of scope

- Booking Form changes.
- Classifier/pipeline redesign.
- Finance Type semantics or Bank DO activation.
- RTO extraction contract.
- Customer Ledger detailed/row-array contract.
- Cheque Photo, Purchase Order, Cash Ledger.
- Accessories/EW exact monetary-field semantics.
- Insurance Actual business semantic decision.
- Trade-in monetary source semantics.
- Audit Core/Web/Security changes.

## Acceptance boundary

Before merge, exact Package-2 head must prove:

- changed-Python lint/type checks used by repository CI;
- fresh PostgreSQL migration through `0027`;
- exactly one global PUBLISHED `booking_docket` profile;
- published Booking Docket retains all baseline fields and includes the four Package-2 keys;
- extraction instructions remain fail-closed/no-inference;
- full backend pytest and any repository frontend/build check pass.

Actual Gemini/document E2E remains a later stabilization verification requirement and is not replaced by source-contract tests.
