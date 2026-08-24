# Verigence DI — Field Evidence Localization v2.4

**Date:** 2026-08-24  
**Status:** UC03 IMPLEMENTATION DESIGN  
**Scope:** Additive positional evidence for extracted fields across all document types

## 1. Purpose

UC03 requires a Process Consultant to validate DI-extracted values against the uploaded source document without re-keying the document. DI therefore returns optional positional evidence for each extracted field so a responsive mobile/tablet UI can show one field at a time and focus the source location.

The initial scope applies to **all document types**, with particular value for handwritten forms. No document type is excluded merely because it is printable. PDF localization is requested as well, with a safe page-only fallback when a reliable bounding box is unavailable.

## 2. Non-negotiable audit rule

Localization is evidence metadata, not a derived business fact.

DI SHALL NOT guess, infer, approximate, or reconstruct a page number or bounding box. If Gemini extracts a value but cannot reliably localize it, DI retains the extracted value and stores localization as null.

An invalid location must never invalidate an otherwise valid extracted value.

## 3. Provider-neutral contract

The existing `FieldResult` contract already provides:

```text
page_no: int | None
evidence_region: dict | None
```

The persisted `extracted_facts` model already provides:

```text
page_no integer
evidence_region jsonb
```

No database migration is required for this increment.

The canonical evidence-region payload for a rectangular source location is:

```json
{
  "type": "BOX_2D",
  "coordinateSystem": "NORMALIZED_1000",
  "box": [120, 85, 176, 438]
}
```

`box` is `[ymin, xmin, ymax, xmax]`, normalized to 0..1000 relative to the relevant rendered page/image. `pageNo` is 1-based.

## 4. Gemini extraction contract

For each configured field DI asks Gemini to return:

```json
{
  "field_key": {
    "value": "...",
    "confidence": "high",
    "pageNo": 1,
    "box_2d": [120, 85, 176, 438]
  }
}
```

When a value is absent:

```json
{
  "field_key": {
    "value": null,
    "confidence": "low",
    "pageNo": null,
    "box_2d": null
  }
}
```

When the value is extractable but its exact location is uncertain, the value remains populated while `pageNo` and/or `box_2d` are null.

## 5. Deterministic validation

DI validates location metadata before persistence.

`pageNo` is accepted only when it is a positive integer.

`box_2d` is accepted only when:

- exactly four numeric coordinates are present;
- every coordinate is within 0..1000;
- `ymin < ymax`;
- `xmin < xmax`.

Anything else is discarded and represented as null. DI never repairs malformed model coordinates.

## 6. Image behavior

For JPEG/PNG/image documents:

- `pageNo` is expected to be 1;
- a valid normalized rectangle may be overlaid directly on the rendered image;
- UI scaling is independent of device size because coordinates are normalized.

This supports responsive mobile and tablet layouts without storing pixel dimensions in the extraction result.

## 7. PDF behavior

Gemini supports native visual PDF understanding and structured extraction. DI therefore requests `pageNo` and `box_2d` for PDF fields as well.

However, PDF rectangle reliability is treated as **best effort until measured with Verigence test evidence**. The runtime contract is therefore:

1. valid `pageNo + evidenceRegion` → UI may navigate to the page and highlight when its PDF renderer supports page-coordinate overlay;
2. valid `pageNo` but no reliable region → UI navigates/focuses the page without drawing a false highlight;
3. neither available → UI still shows the source document and extracted value, with no positional claim.

The absence of PDF localization is not an extraction failure.

## 8. `/fields` API additive extension

The existing document-fields response remains backward compatible. Each current field may additionally include:

```json
{
  "pageNo": 1,
  "evidenceRegion": {
    "type": "BOX_2D",
    "coordinateSystem": "NORMALIZED_1000",
    "box": [120, 85, 176, 438]
  }
}
```

Existing consumers that ignore these optional properties remain unaffected.

For a human-corrected current field value, localization continues to refer to the latest machine-extracted source fact for that document/field. The corrected human value remains separately versioned; localization does not imply that the corrected value was printed at the machine source location.

## 9. UC03 review journey

Audit Core remains the UC03 façade. It may propagate DI localization metadata with an extraction proposal and proxy the original source content for authorized review.

The intended UX is:

```text
Source document + active extracted field
        ↓
focus page / highlight evidence when available
        ↓
PC chooses Correct or Change
        ↓
Next field
        ↓
all required proposals decided
```

The UI is intentionally sequential so it does not need to display every extracted field simultaneously.

### Tablet / wide layout

```text
┌─────────────────────────────┬──────────────────────┐
│ Original document           │ Field 4 of 20        │
│ source location highlighted │ Customer Name        │
│                             │ RAJESH KUMAR         │
│                             │ Correct | Change     │
│                             │ Previous | Next      │
└─────────────────────────────┴──────────────────────┘
```

### Mobile layout

```text
┌─────────────────────────────┐
│ Original document / page    │
│ source location highlighted │
├─────────────────────────────┤
│ Field 4 of 20               │
│ Customer Name               │
│ RAJESH KUMAR                │
│ Correct | Change            │
│ Previous | Next             │
└─────────────────────────────┘
```

## 10. Verification and lineage

Existing UC03 proposal acceptance/correction and DI human-verification semantics remain authoritative.

The machine value must never be overwritten merely because the PC corrects it. A correction remains a separate human decision/version so later audit can show:

- source document;
- machine extracted value;
- machine confidence;
- machine source page/region when available;
- human accepted/corrected value;
- actor and timestamp.

## 11. Observability

Gemini extraction telemetry includes counts for fields with page localization and fields with evidence-region localization. No raw document bytes or extracted PII are added to INFO-level observability.

## 12. Acceptance criteria

This increment is complete when:

- image extraction can persist and return a validated normalized evidence box;
- malformed coordinates are discarded without discarding the field value;
- PDF extraction requests localization and safely supports page-only/no-location fallback;
- `/fields` returns optional localization metadata without breaking existing consumers;
- UC03 Audit Core propagates localization to extraction proposals;
- UC03 can securely retrieve the original source content for the review screen;
- Web/mobile review shows one active field at a time with responsive layout;
- Accept/Correct behavior continues to use existing UC03 decision APIs;
- no guessed coordinates/page numbers are introduced.
