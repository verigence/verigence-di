"""UC02 object-key construction for Audit Core-originated documents."""
from __future__ import annotations

from uuid import UUID

from verigence.di.storage.adapter import _FORM_TYPE_FOLDER, _sanitise_filename, _slugify


def frozen_audit_slugs(
    *,
    tenant_id: str,
    project_name: str | None,
    dealer_name: str | None,
    dealer_outlet_name: str | None,
    customer_name: str | None,
) -> tuple[str, str, str, str]:
    """Reuse D5 slug conventions for immutable Audit storage-context metadata."""
    return (
        _slugify(project_name or tenant_id, 40),
        _slugify(dealer_name or "dealer", 30),
        _slugify(dealer_outlet_name or "outlet", 30),
        _slugify(customer_name or "customer", 30),
    )


def build_audit_original_key(
    *,
    tenant_id: str,
    dealer_id: UUID,
    dealer_outlet_id: UUID,
    customer_id: UUID,
    project_slug: str,
    dealer_slug: str,
    dealer_outlet_slug: str,
    customer_slug: str,
    document_id: UUID,
    physical_form_type: str,
    original_filename: str | None,
    detected_mime_type: str | None = None,
) -> str:
    """Build D28's ID-backed Project/Dealer/Outlet/Customer document key."""
    tenant_short = tenant_id.replace("-", "")[:8]
    dealer_short = dealer_id.hex[:8]
    outlet_short = dealer_outlet_id.hex[:8]
    customer_short = customer_id.hex[:8]
    document_short = document_id.hex[:8]
    form_folder = _FORM_TYPE_FOLDER.get(physical_form_type, "additional")
    safe_filename = _sanitise_filename(
        original_filename,
        fallback_stem=f"{document_short}_{form_folder}",
        mime_type=detected_mime_type,
    )
    if not safe_filename.startswith(document_short):
        safe_filename = f"{document_short}_{safe_filename}"
    return (
        f"{project_slug}-{tenant_short}"
        f"/dealers/{dealer_slug}-{dealer_short}"
        f"/outlets/{dealer_outlet_slug}-{outlet_short}"
        f"/customers/{customer_slug}-{customer_short}"
        f"/documents/{form_folder}"
        f"/{safe_filename}"
    )
