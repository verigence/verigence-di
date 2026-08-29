"""Schema V2 extraction schema for used-vehicle valuation reports.

This Wave-1 type is intentionally early because it exercises EXCHANGE_VEHICLE
role isolation against subject/new-vehicle facts in finance evidence.

The source package also proposes ``valuation_platform``.  The frozen plan moves
that normalized category out of Gemini: DI extracts ``platform_name_as_printed``
and a versioned deterministic ruleset derives the platform category later.
"""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

VALUATION_REPORT_SCHEMA = SchemaDefinition(
    document_type_key="valuation_report",
    display_name="Valuation Report",
    schema_version="2.0",
    fields=[
        FieldSpec("report_number", "string", False, "Valuation report/reference number exactly as printed."),
        FieldSpec("valuation_date", "string", False, "Valuation date; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("valuation_valid_until", "string", False, "Valuation/offer validity end date; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("platform_name_as_printed", "string", False, "Valuation platform/valuer name exactly as printed. The normalized valuation_platform category is derived deterministically outside the model."),
        FieldSpec("evaluator_name", "string", False, "Evaluator/assessor name exactly as printed."),
        FieldSpec("evaluator_employee_code", "string", False, "Evaluator employee/code identifier exactly as printed."),
        FieldSpec("evaluator_signature_present", "boolean", False, "Three-state observation of evaluator signature presence."),
        FieldSpec("registration_number", "string", False, "Registration number of the vehicle being valued."),
        FieldSpec("chassis_number", "string", False, "Chassis/VIN of the vehicle being valued."),
        FieldSpec("make", "string", False, "Vehicle make exactly as printed."),
        FieldSpec("model", "string", False, "Vehicle model exactly as printed."),
        FieldSpec("variant", "string", False, "Vehicle variant exactly as printed."),
        FieldSpec("fuel_type", "string", False, "Fuel type exactly as printed."),
        FieldSpec("manufacture_month_year", "string", False, "Manufacture month/year exactly as printed."),
        FieldSpec("registration_date", "string", False, "Vehicle registration date; normalize to YYYY-MM-DD when unambiguous.", normalization="date_dd_mm_yyyy"),
        FieldSpec("odometer_km", "number", False, "Odometer reading in kilometres as stated."),
        FieldSpec("number_of_owners", "number", False, "Number of owners as stated."),
        FieldSpec("overall_grade", "string", False, "Overall valuation/condition grade exactly as printed."),
        FieldSpec("condition_parameters", "array", False, "JSON array with one object per scored condition parameter, including printed blank rows. Each object: {name: string|null, score_as_printed: string|null, is_blank: boolean}."),
        FieldSpec("accident_history_noted", "boolean", False, "Three-state observation of whether accident history is noted."),
        FieldSpec("accident_remarks", "string", False, "Accident-history remarks exactly as printed."),
        FieldSpec("flood_damage_noted", "boolean", False, "Three-state observation of whether flood damage is noted."),
        FieldSpec("chassis_repair_noted", "boolean", False, "Three-state observation of whether chassis repair is noted."),
        FieldSpec("tyres_condition", "string", False, "Tyre condition exactly as printed."),
        FieldSpec("base_market_value", "number", False, "Base/market value stated on the report."),
        FieldSpec("base_value_source_stated", "string", False, "Source stated for the base value, if any."),
        FieldSpec("depreciation_applied", "number", False, "Depreciation amount/adjustment stated on the report."),
        FieldSpec("condition_deductions", "array", False, "JSON array of deduction rows. Each object: {head: string|null, amount: number|null, is_handwritten: boolean}. Preserve every visible row; do not silently drop malformed/blank rows."),
        FieldSpec("total_deductions_stated", "number", False, "Total deductions stated on the report."),
        FieldSpec("additions", "array", False, "JSON array of addition rows. Each object: {head: string|null, amount: number|null}. Preserve every visible row."),
        FieldSpec("computed_fair_value_stated", "number", False, "Fair/arrived value printed on the report before any final offer."),
        FieldSpec("final_offer_value", "number", False, "Final amount actually offered to the customer as printed."),
        FieldSpec("exchange_bonus_indicated_separately", "number", False, "Exchange bonus shown separately from the valuation, if any."),
        FieldSpec("loan_outstanding_on_vehicle", "number", False, "Outstanding loan amount stated against the exchange vehicle."),
        FieldSpec("photos_attached_count", "number", False, "Count of photos explicitly attached/referenced when determinable."),
        FieldSpec("approval_name", "string", False, "Approver name exactly as printed."),
        FieldSpec("approval_designation", "string", False, "Approver designation exactly as printed."),
        FieldSpec("approval_signature_present", "boolean", False, "Three-state observation of approval signature presence."),
        FieldSpec("override_remark", "string", False, "Override remark exactly as printed, if any."),
        FieldSpec("customer_acceptance_signature", "boolean", False, "Three-state observation of customer acceptance signature presence."),
        FieldSpec("offer_value_handwritten_or_amended", "boolean", False, "Three-state observation of whether the offer value is handwritten or visibly amended."),
        FieldSpec("build_up_absent_only_final_figure_given", "boolean", False, "Three-state observation: true only when the build-up is absent and only a final figure is provided; false when a build-up is clearly present; null when uncertain."),
    ],
    system_prompt=(
        "You extract evidence from used-vehicle valuation reports for dealership audit. "
        "The vehicle being valued is normally the exchange/trade-in vehicle; do not merge "
        "its identifiers with the new/subject vehicle. Extract the report's printed build-up, "
        "deductions, additions and approvals without recomputing them."
    ),
    prompt_notes=[
        "condition_parameters, condition_deductions and additions must be JSON arrays with the exact row shapes described for those fields.",
        "Include printed blank condition rows by setting is_blank=true; never silently omit them.",
        "Do not calculate computed_fair_value_stated from other values; extract the printed figure only.",
        "Do not output valuation_platform; only extract platform_name_as_printed. A deterministic versioned ruleset derives the normalized platform category.",
        "Presence observations are true/false/null and null means unknown/unreadable/ambiguous.",
        "registration_number, chassis_number, make, model and variant belong to the exchange vehicle in the approved Wave-1 profile.",
    ],
)
