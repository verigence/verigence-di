"""Publish the gate_pass profile with the chassis number (gate_pass schema 1.1).

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-16

Closing list item 5 (product owner 2026-11-16, "read what is missing"): the
gate pass reader had no chassis field, so 612 of 621 gate passes on file gave
no VIN and the vehicle that left the gate could not be checked against the
invoice. gate_pass schema 1.1 adds ``chassis_number`` (optional); this
publishes the matching profile (the published fields carried over unchanged
plus the new one) and retires the old one. Published profiles are immutable,
hence a new version. Form 21's VIN instruction (form_21 schema 1.1) asks for
the full VIN when both the short and the full number are printed; its keys
are unchanged, so its profile is not republished.

NOTHING IS RE-EXTRACTED here. Forward-only, like 0061.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

_ACTOR = "migration.0068.gate-pass-chassis"
_TYPE_KEY = "gate_pass"

# (field_key, canonical data_type, instruction, expected, display_sequence)
# Snapshot of GATE_PASS_SCHEMA 1.1 (a migration must not import app code);
# tests/test_gate_pass_chassis_profile.py pins it to the schema. A field the
# published profile already has keeps its published instruction.
_FIELDS: tuple[tuple[str, str, str, bool, int], ...] = (
    ("delivery_date", "DATE", "Delivery/gate-pass date exactly as printed; normalize only when unambiguous.", False, 10),
    ("car_number_as_printed", "STRING",
     "Car/vehicle number exactly as printed, without assuming what identifier type it is.", False, 20),
    ("vehicle_registration_number", "IDENTIFIER",
     "Vehicle registration number only when the document explicitly labels the value as registration number or "
     "the printed format is unambiguously a registration number.", False, 30),
    ("chassis_number", "IDENTIFIER",
     "Chassis number / VIN of the vehicle exactly as printed or written (Chassis No., VIN, Frame No.); the full "
     "17 characters when printed, otherwise the part printed; never correct or complete characters.", False, 40),
)


def _publisher():
    """The cost sheet migration's republishing steps (0061), reused with this
    type, actor and snapshot."""
    path = Path(__file__).resolve().parent / "0061_cost_sheet_rows.py"
    spec = importlib.util.spec_from_file_location("mig_0061_publisher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._ACTOR = _ACTOR
    module._TYPE_KEY = _TYPE_KEY
    module._FIELDS = _FIELDS
    module._OLD_KEY_FOR = {}
    return module


def upgrade() -> None:
    _publisher().upgrade()


def downgrade() -> None:
    # Published configuration is immutable; forward-only (as 0061).
    pass
