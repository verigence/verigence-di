# Schema V2 — Wave 1 Semantic Mapping

**Status:** FROZEN FOR WAVE-1 DRAFT PROFILE IMPLEMENTATION  
**Date:** 29-Aug-2026  
**Source:** frozen 18-document package + frozen implementation plan.

This mapping is deliberately semantic rather than string-similarity based. `extraction_key` is the source/package key sent to the provider; `canonical_field` is the stable DI business vocabulary. `fact_role` is frozen onto each emitted fact.

The original package declares several observation booleans as plain `boolean`. The frozen implementation plan explicitly amends evidence-presence observations to three-state `true / false / null`; Wave-1 prompts, profiles and rules follow that amendment.

## Defaults and important decisions

- `GST_CERTIFICATE` default role: `ORGANISATION`.
- `CORPORATE_ID` default role: `UNSPECIFIED`; employer/person/document facts use field overrides.
- `BANK_APPROVAL_LETTER` default role: `SUBJECT_TRANSACTION`; vehicle and financier fields use overrides.
- `VALUATION_REPORT` default role: `EXCHANGE_VEHICLE`; evaluator/platform/approval/customer facts use overrides.
- `valuation_platform` is **not a Gemini extraction target**. Only `platform_name_as_printed` is extracted; a versioned deterministic ruleset derives the normalized platform category.
- `financier_type` is retained in the source matrix but classified as `REFERENCE`: resolve it from the financier master/name where possible rather than asking Gemini to invent an institutional category.
- Structured rows are parsed with `schema_v2.structured_literal_parse` and validated with `schema_v2.structured_shape`; malformed rows are surfaced, never silently dropped.

## GST_CERTIFICATE

| extraction_key | canonical_field | role | source class | canonical type | implementation note |
|---|---|---|---|---|---|
| `gstin` | `gstin` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `legal_name` | `organisation_legal_name` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `trade_name` | `organisation_trade_name` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `constitution_of_business` | `organisation_constitution` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `address_principal_place` | `organisation_principal_address` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `state` | `organisation_address_state` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `pincode` | `organisation_address_pincode` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `type_of_registration` | `gst_registration_type` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `date_of_liability` | `gst_date_of_liability` | `ORGANISATION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `period_of_validity_from` | `gst_valid_from` | `ORGANISATION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `period_of_validity_to` | `gst_valid_to_text` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `date_of_issue` | `gst_certificate_issue_date` | `ORGANISATION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `jurisdiction_state` | `gst_jurisdiction_state` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `jurisdiction_centre` | `gst_jurisdiction_centre` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `authorised_signatory_names` | `gst_authorised_signatory_names` | `ORGANISATION` | `EVIDENCE` | `JSON` | Structured JSON; deterministic parse + shape validation. |
| `cancellation_or_suspension_text` | `gst_cancellation_or_suspension_text` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `has_digital_signature` | `gst_digital_signature_present` | `ORGANISATION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |

## CORPORATE_ID

| extraction_key | canonical_field | role | source class | canonical type | implementation note |
|---|---|---|---|---|---|
| `evidence_format` | `corporate_evidence_format` | `UNSPECIFIED` | `EVIDENCE` | `STRING` | Raw document statement. |
| `employer_name` | `employer_name` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `employer_address` | `employer_address` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `employer_gstin_printed` | `employer_gstin` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `employee_name` | `employee_name` | `CUSTOMER` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `employee_code` | `employee_code` | `CUSTOMER` | `EVIDENCE` | `STRING` | Raw document statement. |
| `designation` | `employment_designation` | `CUSTOMER` | `EVIDENCE` | `STRING` | Raw document statement. |
| `department` | `employment_department` | `CUSTOMER` | `EVIDENCE` | `STRING` | Raw document statement. |
| `date_of_joining` | `employment_date_of_joining` | `CUSTOMER` | `EVIDENCE` | `DATE` | Raw document statement. |
| `id_valid_from` | `corporate_evidence_valid_from` | `CUSTOMER` | `EVIDENCE` | `DATE` | Raw document statement. |
| `id_valid_until` | `corporate_evidence_valid_until` | `CUSTOMER` | `EVIDENCE` | `DATE` | Raw document statement. |
| `document_date` | `corporate_evidence_document_date` | `UNSPECIFIED` | `EVIDENCE` | `DATE` | Raw document statement. |
| `salary_slip_month` | `salary_slip_month` | `CUSTOMER` | `EVIDENCE` | `STRING` | Raw document statement. |
| `corporate_scheme_code_referenced` | `corporate_scheme_code_referenced` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `photo_present` | `corporate_photo_present` | `CUSTOMER` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `employer_logo_present` | `corporate_employer_logo_present` | `ORGANISATION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `issuing_authority_signature_present` | `corporate_issuing_signature_present` | `ORGANISATION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `is_photocopy` | `corporate_evidence_is_photocopy` | `UNSPECIFIED` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |

## BANK_APPROVAL_LETTER

| extraction_key | canonical_field | role | source class | canonical type | implementation note |
|---|---|---|---|---|---|
| `financier_name` | `financier_name` | `ORGANISATION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `financier_type` | `financier_type` | `ORGANISATION` | `REFERENCE` | `STRING` | Use authoritative financier/master classification; keep printed financier name as evidence. |
| `branch` | `financier_branch` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `sanction_letter_number` | `finance_sanction_letter_number` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `sanction_date` | `finance_sanction_date` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `offer_valid_until` | `finance_offer_valid_until` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `applicant_name` | `finance_applicant_name` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `applicant_pan` | `finance_applicant_pan` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `co_applicant_name` | `finance_co_applicant_name` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `guarantor_name` | `finance_guarantor_name` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `loan_account_or_application_number` | `finance_application_number` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `chassis_number` | `chassis_number` | `SUBJECT_VEHICLE` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `make_model_variant` | `vehicle_make_model_variant_text` | `SUBJECT_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `ex_showroom_considered` | `finance_ex_showroom_considered` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `on_road_price_considered` | `finance_on_road_price_considered` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `insurance_considered` | `finance_insurance_considered` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `accessories_considered` | `finance_accessories_considered` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `invoice_or_proforma_value_referenced` | `finance_invoice_or_proforma_value` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `proforma_reference_number` | `finance_proforma_reference_number` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `sanctioned_amount` | `finance_sanctioned_amount` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `ltv_percent_stated` | `finance_ltv_percent_stated` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `DECIMAL` | Raw document statement. |
| `margin_money_required` | `finance_margin_money_required` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `tenure_months` | `finance_tenure_months` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `INTEGER` | Raw document statement. |
| `interest_rate` | `finance_interest_rate` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `DECIMAL` | Raw document statement. |
| `rate_type` | `finance_rate_type` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `emi_amount` | `finance_emi_amount` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `processing_fee` | `finance_processing_fee` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `insurance_funded` | `finance_insurance_funded` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `subvention_scheme_referenced` | `finance_subvention_scheme_referenced` | `SUBJECT_TRANSACTION` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `subvention_borne_by_stated` | `finance_subvention_borne_by_stated` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `subvention_amount` | `finance_subvention_amount` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `dealer_payout_amount` | `finance_dealer_payout_amount` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `disbursement_in_favour_of` | `finance_disbursement_in_favour_of` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `disbursement_mode` | `finance_disbursement_mode` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `disbursement_date` | `finance_disbursement_date` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `DATE` | Raw document statement. |
| `conditions_precedent` | `finance_conditions_precedent` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `JSON` | Structured JSON; deterministic parse + shape validation. |
| `signature_present` | `finance_approval_signature_present` | `SUBJECT_TRANSACTION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |

## VALUATION_REPORT

| extraction_key | canonical_field | role | source class | canonical type | implementation note |
|---|---|---|---|---|---|
| `report_number` | `valuation_report_number` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `valuation_date` | `valuation_date` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `DATE` | Raw document statement. |
| `valuation_valid_until` | `valuation_valid_until` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `DATE` | Raw document statement. |
| `valuation_platform` | `valuation_platform` | `ORGANISATION` | `DERIVED` | `STRING` | Derived deterministically from `platform_name_as_printed`; no profile field for this key. |
| `platform_name_as_printed` | `valuation_platform_name_printed` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `evaluator_name` | `valuation_evaluator_name` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `evaluator_employee_code` | `valuation_evaluator_employee_code` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `evaluator_signature_present` | `valuation_evaluator_signature_present` | `ORGANISATION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `registration_number` | `vehicle_registration_number` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `chassis_number` | `chassis_number` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `IDENTIFIER` | Raw document statement. |
| `make` | `vehicle_make` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `model` | `vehicle_model` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `variant` | `vehicle_variant` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `fuel_type` | `vehicle_fuel_type` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `manufacture_month_year` | `vehicle_manufacture_month_year` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `STRING` | Raw document statement. |
| `registration_date` | `vehicle_registration_date` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `DATE` | Raw document statement. |
| `odometer_km` | `vehicle_odometer_km` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `DECIMAL` | Raw document statement. |
| `number_of_owners` | `vehicle_owner_count` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `INTEGER` | Raw document statement. |
| `overall_grade` | `valuation_overall_grade` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `condition_parameters` | `valuation_condition_parameters` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `JSON` | Structured JSON; deterministic parse + shape validation. |
| `accident_history_noted` | `vehicle_accident_history_noted` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `accident_remarks` | `vehicle_accident_remarks` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `flood_damage_noted` | `vehicle_flood_damage_noted` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `chassis_repair_noted` | `vehicle_chassis_repair_noted` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `tyres_condition` | `vehicle_tyres_condition` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `base_market_value` | `valuation_base_market_value` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `base_value_source_stated` | `valuation_base_value_source_stated` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `depreciation_applied` | `valuation_depreciation_applied` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `condition_deductions` | `valuation_condition_deductions` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `JSON` | Structured JSON; deterministic parse + shape validation. |
| `total_deductions_stated` | `valuation_total_deductions_stated` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `additions` | `valuation_additions` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `JSON` | Structured JSON; deterministic parse + shape validation. |
| `computed_fair_value_stated` | `valuation_computed_fair_value_stated` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `final_offer_value` | `valuation_final_offer_value` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `exchange_bonus_indicated_separately` | `valuation_exchange_bonus_separate` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `CURRENCY` | Raw document statement. |
| `loan_outstanding_on_vehicle` | `exchange_vehicle_loan_outstanding` | `EXCHANGE_VEHICLE` | `EXTRACT_AND_COMPARE` | `CURRENCY` | Raw document statement. |
| `photos_attached_count` | `valuation_photos_attached_count` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `INTEGER` | Raw document statement. |
| `approval_name` | `valuation_approval_name` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `approval_designation` | `valuation_approval_designation` | `ORGANISATION` | `EVIDENCE` | `STRING` | Raw document statement. |
| `approval_signature_present` | `valuation_approval_signature_present` | `ORGANISATION` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `override_remark` | `valuation_override_remark` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `STRING` | Raw document statement. |
| `customer_acceptance_signature` | `valuation_customer_acceptance_signature` | `CUSTOMER` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `offer_value_handwritten_or_amended` | `valuation_offer_value_handwritten_or_amended` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |
| `build_up_absent_only_final_figure_given` | `valuation_build_up_absent_only_final` | `EXCHANGE_VEHICLE` | `EVIDENCE` | `BOOLEAN` | Three-state evidence observation per frozen-plan amendment. |

## Wave-1 control/source intent

- `EXTRACT_AND_COMPARE` means the document statement is preserved as evidence **and** Audit Core compares it with the appropriate journey/DMS/master/other-evidence value. Extraction does not decide whether the difference is a finding.
- `EVIDENCE` means the printed/observed fact itself is an audit input; no authoritative replacement should overwrite it.
- `REFERENCE` means the normalized category should come from deterministic/master data, while related raw text remains evidence.
- `DERIVED` means the business category is produced by versioned deterministic logic from one or more extracted raw facts.

## Structured row contracts used by Wave 1

- `GST_CERTIFICATE.authorised_signatory_names`: `array[string]`.
- `BANK_APPROVAL_LETTER.conditions_precedent`: `array[string]`.
- `VALUATION_REPORT.condition_parameters`: every row carries `name: string|null`, `score_as_printed: string|null`, `is_blank: boolean`.
- `VALUATION_REPORT.condition_deductions`: every row carries `head: string|null`, `amount: number|null`, `is_handwritten: boolean`.
- `VALUATION_REPORT.additions`: every row carries `head: string|null`, `amount: number|null`.

## Publication gate for these profiles

The Wave-1 profiles remain DRAFT until runtime uses provider-facing `extraction_key` safely, structured validation can force review on ERROR-level failures, DI exposes role/lineage in the Audit integration contract, and the cross-document `chassis_number` role-isolation test passes (`SUBJECT_VEHICLE` from Bank Approval vs `EXCHANGE_VEHICLE` from Valuation Report).
