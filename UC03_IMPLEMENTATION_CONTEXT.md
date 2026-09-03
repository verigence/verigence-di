# UC03 Implementation Context — DI RTO Final-Report Contract Package 3

Repository: `verigence-di`
Branch: `fix/uc03-di-rto-final-report-v1`
Base: `dev` at `71ff26c7bc61da95e7bc04c615a7cae698bb1312`
Mode: UC03 stabilization continuation authorized by the user on 2026-09-03; do not pause for routine write/merge/deploy steps while this exact scope remains green and contained.

## Governing rules

- UC03 stabilization only; no unrelated cleanup or redesign.
- Work one evidence-backed unit at a time.
- Preserve existing DI fact/provenance behavior and backward compatibility.
- `rto_challan` is the existing UC03 catalogue identity for the RTO paper/challan evidence source.
- Runtime extraction requires both a registered provider-neutral schema and a published DB extraction profile.
- No classifier or worker-orchestration redesign.
- No Audit Core, Web, or Security changes on this branch.
- Merge to `dev` uses the repository's normal CI/deployment behavior.
- Stop if implementation requires scope outside this RTO contract.

## Verified current state

- Migration `0016` created active global document type `rto_challan` and existing tenant catalogue rows with `requires_processing=false` because no extraction profile was published.
- `SCHEMA_REGISTRY` has no `rto_challan` entry, so provider extraction currently falls back rather than using an RTO-specific contract.
- Audit Core final-source stabilization still blocks the RTO source because canonical field keys are not proven.

## Package 3 scope

Publish one immutable global `rto_challan` extraction profile and activate processing for existing tenants. Add one provider-neutral RTO schema with only these final-report evidence fields:

1. `registration_number` — IDENTIFIER / schema string — vehicle registration number only when explicitly printed/labeled.
2. `registration_state` — STRING — State only when explicitly printed as registration/RTO state; never infer from registration number.
3. `registration_territory` — STRING — Territory/UT only when explicitly printed; never derive it from state, registration number or geography knowledge.
4. `registration_district` — STRING — District/RTO district only when explicitly printed; never infer from RTO code or geography knowledge.
5. `ex_showroom_amount` — CURRENCY / schema number — ex-showroom amount only when explicitly labelled and printed; never calculate from totals or taxes.
6. `registration_type` — STRING — registration type/category exactly as printed; never classify from vehicle/customer/finance context.
7. `hp_charges_amount` — CURRENCY / schema number — hypothecation/HP charges only when explicitly labelled and printed; never derive from finance details.

Use additive migration `0028` after current head `0027`. Historical facts/profile rows remain immutable. Existing tenant `rto_challan` catalogue rows become `requires_processing=true` only after the profile is published.

## Explicitly out of scope

- `vehicle_rc` extraction changes.
- Any RTO-rule or registration business logic.
- Registration-number decoding to state/district/territory.
- Classifier/pipeline redesign.
- Finance Type or Bank DO.
- Customer Ledger detailed contract.
- Accessories/EW/Insurance semantic decisions.
- Audit Core/Web/Security changes.

## Acceptance boundary

Before merge, exact Package-3 head must prove:

- changed-Python lint/type checks used by repository CI;
- `rto_challan` is present in `SCHEMA_REGISTRY` with the seven expected schema keys;
- fresh PostgreSQL migration through `0028`;
- exactly one global PUBLISHED `rto_challan` profile;
- published profile contains exactly the required seven RTO final-report evidence keys at minimum;
- existing tenant `rto_challan` catalogue rows require processing and remain active;
- extraction instructions are explicit/fail-closed and prohibit inference/calculation;
- full backend pytest and repository frontend/build checks pass;
- post-merge DEV deployment and smoke pass before the paired Audit Core mapping is merged.

Actual Gemini/document E2E remains a later stabilization verification requirement and is not replaced by source-contract tests.
