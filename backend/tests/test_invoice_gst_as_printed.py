"""GST is read as printed, not from the model's memory of the old slabs (2026-10-28).

An Aditya Motors invoice printed CGST 20% / SGST 20% (Rs 2,41,414.34 each, 40% in
all, no cess). It was read as CGST 14% / SGST 14% (Rs 1,68,990 each) plus a cess
of Rs 1,44,848.68: the pre-September-2025 split of the same 40%. Every invoice
schema now tells the reader so."""
from __future__ import annotations

import pytest

from verigence.di.document_ai.schemas import get_schema

pytestmark = pytest.mark.no_docker


@pytest.mark.parametrize("document_type_key", [
    "customer_invoice_dms", "tax_invoice_tally", "wholesale_invoice", "accessory_invoice_dms",
    "accessory_invoice_tally", "ew_invoice", "rsa_invoice", "credit_note", "invoice_generic",
])
def test_every_invoice_is_told_to_copy_gst_as_printed(document_type_key: str) -> None:
    notes = " ".join(get_schema(document_type_key).prompt_notes)
    assert "Never split a GST total into CGST, SGST and cess" in notes
    assert "22 September 2025" in notes and "compensation cess is gone" in notes
