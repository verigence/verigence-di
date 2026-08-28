"""Seed Schema V2 Wave-1 canonical vocabulary and DRAFT profiles.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-29

This migration is configuration-only.  It does NOT publish extraction profiles
and therefore does not alter the classification candidate set.  The source of
truth is docs/schema-v2/WAVE1_SEMANTIC_MAPPING_v0.1.md.

The migration is intentionally idempotent because the Schema V2 Neon sandbox is
being exercised while the historical DI Alembic marker is reconciled separately.
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_PROFILE_NAME = 'Schema V2 Wave 1 Draft'
_DOCUMENT_TYPES = (('gst_certificate', 'GST Certificate', 'PRINTABLE'),
 ('corporate_id', 'Corporate ID', 'PRINTABLE'),
 ('bank_approval_letter', 'Bank Approval Letter', 'PRINTABLE'),
 ('valuation_report', 'Valuation Report', 'PRINTABLE'))

# field_key, display_name, data_type
_CANONICAL_FIELDS = (('chassis_number', 'Chassis Number', 'IDENTIFIER'),
 ('corporate_employer_logo_present', 'Corporate Employer Logo Present', 'BOOLEAN'),
 ('corporate_evidence_document_date', 'Corporate Evidence Document Date', 'DATE'),
 ('corporate_evidence_format', 'Corporate Evidence Format', 'STRING'),
 ('corporate_evidence_is_photocopy', 'Corporate Evidence Is Photocopy', 'BOOLEAN'),
 ('corporate_evidence_valid_from', 'Corporate Evidence Valid From', 'DATE'),
 ('corporate_evidence_valid_until', 'Corporate Evidence Valid Until', 'DATE'),
 ('corporate_issuing_signature_present', 'Corporate Issuing Signature Present', 'BOOLEAN'),
 ('corporate_photo_present', 'Corporate Photo Present', 'BOOLEAN'),
 ('corporate_scheme_code_referenced', 'Corporate Scheme Code Referenced', 'STRING'),
 ('employer_address', 'Employer Address', 'STRING'),
 ('employer_gstin', 'Employer Gstin', 'IDENTIFIER'),
 ('employer_name', 'Employer Name', 'STRING'),
 ('employee_code', 'Employee Code', 'STRING'),
 ('employee_name', 'Employee Name', 'STRING'),
 ('employment_date_of_joining', 'Employment Date Of Joining', 'DATE'),
 ('employment_department', 'Employment Department', 'STRING'),
 ('employment_designation', 'Employment Designation', 'STRING'),
 ('exchange_vehicle_loan_outstanding', 'Exchange Vehicle Loan Outstanding', 'CURRENCY'),
 ('finance_accessories_considered', 'Finance Accessories Considered', 'CURRENCY'),
 ('finance_applicant_name', 'Finance Applicant Name', 'STRING'),
 ('finance_applicant_pan', 'Finance Applicant Pan', 'IDENTIFIER'),
 ('finance_approval_signature_present', 'Finance Approval Signature Present', 'BOOLEAN'),
 ('finance_co_applicant_name', 'Finance Co Applicant Name', 'STRING'),
 ('finance_conditions_precedent', 'Finance Conditions Precedent', 'JSON'),
 ('finance_dealer_payout_amount', 'Finance Dealer Payout Amount', 'CURRENCY'),
 ('finance_disbursement_date', 'Finance Disbursement Date', 'DATE'),
 ('finance_disbursement_in_favour_of', 'Finance Disbursement In Favour Of', 'STRING'),
 ('finance_disbursement_mode', 'Finance Disbursement Mode', 'STRING'),
 ('finance_emi_amount', 'Finance Emi Amount', 'CURRENCY'),
 ('finance_ex_showroom_considered', 'Finance Ex Showroom Considered', 'CURRENCY'),
 ('finance_guarantor_name', 'Finance Guarantor Name', 'STRING'),
 ('finance_insurance_considered', 'Finance Insurance Considered', 'CURRENCY'),
 ('finance_insurance_funded', 'Finance Insurance Funded', 'BOOLEAN'),
 ('finance_interest_rate', 'Finance Interest Rate', 'DECIMAL'),
 ('finance_invoice_or_proforma_value', 'Finance Invoice Or Proforma Value', 'CURRENCY'),
 ('finance_ltv_percent_stated', 'Finance Ltv Percent Stated', 'DECIMAL'),
 ('finance_margin_money_required', 'Finance Margin Money Required', 'CURRENCY'),
 ('finance_offer_valid_until', 'Finance Offer Valid Until', 'DATE'),
 ('finance_on_road_price_considered', 'Finance On Road Price Considered', 'CURRENCY'),
 ('finance_processing_fee', 'Finance Processing Fee', 'CURRENCY'),
 ('finance_proforma_reference_number', 'Finance Proforma Reference Number', 'STRING'),
 ('finance_rate_type', 'Finance Rate Type', 'STRING'),
 ('finance_sanction_date', 'Finance Sanction Date', 'DATE'),
 ('finance_sanction_letter_number', 'Finance Sanction Letter Number', 'STRING'),
 ('finance_sanctioned_amount', 'Finance Sanctioned Amount', 'CURRENCY'),
 ('finance_subvention_amount', 'Finance Subvention Amount', 'CURRENCY'),
 ('finance_subvention_borne_by_stated', 'Finance Subvention Borne By Stated', 'STRING'),
 ('finance_subvention_scheme_referenced', 'Finance Subvention Scheme Referenced', 'STRING'),
 ('finance_tenure_months', 'Finance Tenure Months', 'INTEGER'),
 ('financier_branch', 'Financier Branch', 'STRING'),
 ('financier_name', 'Financier Name', 'STRING'),
 ('gst_authorised_signatory_names', 'Gst Authorised Signatory Names', 'JSON'),
 ('gst_cancellation_or_suspension_text', 'Gst Cancellation Or Suspension Text', 'STRING'),
 ('gst_certificate_issue_date', 'Gst Certificate Issue Date', 'DATE'),
 ('gst_date_of_liability', 'Gst Date Of Liability', 'DATE'),
 ('gst_digital_signature_present', 'Gst Digital Signature Present', 'BOOLEAN'),
 ('gst_jurisdiction_centre', 'Gst Jurisdiction Centre', 'STRING'),
 ('gst_jurisdiction_state', 'Gst Jurisdiction State', 'STRING'),
 ('gst_registration_type', 'Gst Registration Type', 'STRING'),
 ('gst_valid_from', 'Gst Valid From', 'DATE'),
 ('gst_valid_to_text', 'Gst Valid To Text', 'STRING'),
 ('gstin', 'Gstin', 'IDENTIFIER'),
 ('organisation_address_pincode', 'Organisation Address Pincode', 'STRING'),
 ('organisation_address_state', 'Organisation Address State', 'STRING'),
 ('organisation_constitution', 'Organisation Constitution', 'STRING'),
 ('organisation_legal_name', 'Organisation Legal Name', 'STRING'),
 ('organisation_principal_address', 'Organisation Principal Address', 'STRING'),
 ('organisation_trade_name', 'Organisation Trade Name', 'STRING'),
 ('salary_slip_month', 'Salary Slip Month', 'STRING'),
 ('valuation_additions', 'Valuation Additions', 'JSON'),
 ('valuation_approval_designation', 'Valuation Approval Designation', 'STRING'),
 ('valuation_approval_name', 'Valuation Approval Name', 'STRING'),
 ('valuation_approval_signature_present', 'Valuation Approval Signature Present', 'BOOLEAN'),
 ('valuation_base_market_value', 'Valuation Base Market Value', 'CURRENCY'),
 ('valuation_base_value_source_stated', 'Valuation Base Value Source Stated', 'STRING'),
 ('valuation_build_up_absent_only_final', 'Valuation Build Up Absent Only Final', 'BOOLEAN'),
 ('valuation_computed_fair_value_stated', 'Valuation Computed Fair Value Stated', 'CURRENCY'),
 ('valuation_condition_deductions', 'Valuation Condition Deductions', 'JSON'),
 ('valuation_condition_parameters', 'Valuation Condition Parameters', 'JSON'),
 ('valuation_customer_acceptance_signature', 'Valuation Customer Acceptance Signature', 'BOOLEAN'),
 ('valuation_date', 'Valuation Date', 'DATE'),
 ('valuation_depreciation_applied', 'Valuation Depreciation Applied', 'CURRENCY'),
 ('valuation_evaluator_employee_code', 'Valuation Evaluator Employee Code', 'STRING'),
 ('valuation_evaluator_name', 'Valuation Evaluator Name', 'STRING'),
 ('valuation_evaluator_signature_present', 'Valuation Evaluator Signature Present', 'BOOLEAN'),
 ('valuation_exchange_bonus_separate', 'Valuation Exchange Bonus Separate', 'CURRENCY'),
 ('valuation_final_offer_value', 'Valuation Final Offer Value', 'CURRENCY'),
 ('valuation_offer_value_handwritten_or_amended', 'Valuation Offer Value Handwritten Or Amended', 'BOOLEAN'),
 ('valuation_overall_grade', 'Valuation Overall Grade', 'STRING'),
 ('valuation_override_remark', 'Valuation Override Remark', 'STRING'),
 ('valuation_photos_attached_count', 'Valuation Photos Attached Count', 'INTEGER'),
 ('valuation_platform_name_printed', 'Valuation Platform Name Printed', 'STRING'),
 ('valuation_report_number', 'Valuation Report Number', 'STRING'),
 ('valuation_total_deductions_stated', 'Valuation Total Deductions Stated', 'CURRENCY'),
 ('valuation_valid_until', 'Valuation Valid Until', 'DATE'),
 ('vehicle_accident_history_noted', 'Vehicle Accident History Noted', 'BOOLEAN'),
 ('vehicle_accident_remarks', 'Vehicle Accident Remarks', 'STRING'),
 ('vehicle_chassis_repair_noted', 'Vehicle Chassis Repair Noted', 'BOOLEAN'),
 ('vehicle_flood_damage_noted', 'Vehicle Flood Damage Noted', 'BOOLEAN'),
 ('vehicle_fuel_type', 'Vehicle Fuel Type', 'STRING'),
 ('vehicle_make', 'Vehicle Make', 'STRING'),
 ('vehicle_make_model_variant_text', 'Vehicle Make Model Variant Text', 'STRING'),
 ('vehicle_manufacture_month_year', 'Vehicle Manufacture Month Year', 'STRING'),
 ('vehicle_model', 'Vehicle Model', 'STRING'),
 ('vehicle_odometer_km', 'Vehicle Odometer Km', 'DECIMAL'),
 ('vehicle_owner_count', 'Vehicle Owner Count', 'INTEGER'),
 ('vehicle_registration_date', 'Vehicle Registration Date', 'DATE'),
 ('vehicle_registration_number', 'Vehicle Registration Number', 'IDENTIFIER'),
 ('vehicle_tyres_condition', 'Vehicle Tyres Condition', 'STRING'),
 ('vehicle_variant', 'Vehicle Variant', 'STRING'))

# document_type_key, extraction_key, canonical_field_key, fact_role, source_class, canonical_type
# REFERENCE and DERIVED source rows are deliberately absent: they are not Gemini extraction targets.
_PROFILE_FIELDS = (('gst_certificate', 'gstin', 'gstin', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('gst_certificate', 'legal_name', 'organisation_legal_name', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'trade_name', 'organisation_trade_name', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'constitution_of_business', 'organisation_constitution', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'address_principal_place', 'organisation_principal_address', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'state', 'organisation_address_state', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'pincode', 'organisation_address_pincode', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('gst_certificate', 'type_of_registration', 'gst_registration_type', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('gst_certificate', 'date_of_liability', 'gst_date_of_liability', 'ORGANISATION', 'EVIDENCE', 'DATE'),
 ('gst_certificate', 'period_of_validity_from', 'gst_valid_from', 'ORGANISATION', 'EVIDENCE', 'DATE'),
 ('gst_certificate', 'period_of_validity_to', 'gst_valid_to_text', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('gst_certificate', 'date_of_issue', 'gst_certificate_issue_date', 'ORGANISATION', 'EVIDENCE', 'DATE'),
 ('gst_certificate', 'jurisdiction_state', 'gst_jurisdiction_state', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('gst_certificate', 'jurisdiction_centre', 'gst_jurisdiction_centre', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('gst_certificate', 'authorised_signatory_names', 'gst_authorised_signatory_names', 'ORGANISATION', 'EVIDENCE', 'JSON'),
 ('gst_certificate', 'cancellation_or_suspension_text', 'gst_cancellation_or_suspension_text', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('gst_certificate', 'has_digital_signature', 'gst_digital_signature_present', 'ORGANISATION', 'EVIDENCE', 'BOOLEAN'),
 ('corporate_id', 'evidence_format', 'corporate_evidence_format', 'UNSPECIFIED', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'employer_name', 'employer_name', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('corporate_id', 'employer_address', 'employer_address', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'employer_gstin_printed', 'employer_gstin', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('corporate_id', 'employee_name', 'employee_name', 'CUSTOMER', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('corporate_id', 'employee_code', 'employee_code', 'CUSTOMER', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'designation', 'employment_designation', 'CUSTOMER', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'department', 'employment_department', 'CUSTOMER', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'date_of_joining', 'employment_date_of_joining', 'CUSTOMER', 'EVIDENCE', 'DATE'),
 ('corporate_id', 'id_valid_from', 'corporate_evidence_valid_from', 'CUSTOMER', 'EVIDENCE', 'DATE'),
 ('corporate_id', 'id_valid_until', 'corporate_evidence_valid_until', 'CUSTOMER', 'EVIDENCE', 'DATE'),
 ('corporate_id', 'document_date', 'corporate_evidence_document_date', 'UNSPECIFIED', 'EVIDENCE', 'DATE'),
 ('corporate_id', 'salary_slip_month', 'salary_slip_month', 'CUSTOMER', 'EVIDENCE', 'STRING'),
 ('corporate_id', 'corporate_scheme_code_referenced', 'corporate_scheme_code_referenced', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('corporate_id', 'photo_present', 'corporate_photo_present', 'CUSTOMER', 'EVIDENCE', 'BOOLEAN'),
 ('corporate_id', 'employer_logo_present', 'corporate_employer_logo_present', 'ORGANISATION', 'EVIDENCE', 'BOOLEAN'),
 ('corporate_id', 'issuing_authority_signature_present', 'corporate_issuing_signature_present', 'ORGANISATION', 'EVIDENCE', 'BOOLEAN'),
 ('corporate_id', 'is_photocopy', 'corporate_evidence_is_photocopy', 'UNSPECIFIED', 'EVIDENCE', 'BOOLEAN'),
 ('bank_approval_letter', 'financier_name', 'financier_name', 'ORGANISATION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('bank_approval_letter', 'branch', 'financier_branch', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'sanction_letter_number', 'finance_sanction_letter_number', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'sanction_date', 'finance_sanction_date', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'DATE'),
 ('bank_approval_letter', 'offer_valid_until', 'finance_offer_valid_until', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'DATE'),
 ('bank_approval_letter', 'applicant_name', 'finance_applicant_name', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('bank_approval_letter', 'applicant_pan', 'finance_applicant_pan', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('bank_approval_letter', 'co_applicant_name', 'finance_co_applicant_name', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'guarantor_name', 'finance_guarantor_name', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'loan_account_or_application_number', 'finance_application_number', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'chassis_number', 'chassis_number', 'SUBJECT_VEHICLE', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('bank_approval_letter', 'make_model_variant', 'vehicle_make_model_variant_text', 'SUBJECT_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('bank_approval_letter', 'ex_showroom_considered', 'finance_ex_showroom_considered', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('bank_approval_letter', 'on_road_price_considered', 'finance_on_road_price_considered', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('bank_approval_letter', 'insurance_considered', 'finance_insurance_considered', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('bank_approval_letter', 'accessories_considered', 'finance_accessories_considered', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('bank_approval_letter', 'invoice_or_proforma_value_referenced', 'finance_invoice_or_proforma_value', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('bank_approval_letter', 'proforma_reference_number', 'finance_proforma_reference_number', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('bank_approval_letter', 'sanctioned_amount', 'finance_sanctioned_amount', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'ltv_percent_stated', 'finance_ltv_percent_stated', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'DECIMAL'),
 ('bank_approval_letter', 'margin_money_required', 'finance_margin_money_required', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'tenure_months', 'finance_tenure_months', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'INTEGER'),
 ('bank_approval_letter', 'interest_rate', 'finance_interest_rate', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'DECIMAL'),
 ('bank_approval_letter', 'rate_type', 'finance_rate_type', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'emi_amount', 'finance_emi_amount', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'processing_fee', 'finance_processing_fee', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'insurance_funded', 'finance_insurance_funded', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'BOOLEAN'),
 ('bank_approval_letter', 'subvention_scheme_referenced', 'finance_subvention_scheme_referenced', 'SUBJECT_TRANSACTION', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('bank_approval_letter', 'subvention_borne_by_stated', 'finance_subvention_borne_by_stated', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'subvention_amount', 'finance_subvention_amount', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'dealer_payout_amount', 'finance_dealer_payout_amount', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'CURRENCY'),
 ('bank_approval_letter', 'disbursement_in_favour_of', 'finance_disbursement_in_favour_of', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'disbursement_mode', 'finance_disbursement_mode', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'STRING'),
 ('bank_approval_letter', 'disbursement_date', 'finance_disbursement_date', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'DATE'),
 ('bank_approval_letter', 'conditions_precedent', 'finance_conditions_precedent', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'JSON'),
 ('bank_approval_letter', 'signature_present', 'finance_approval_signature_present', 'SUBJECT_TRANSACTION', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'report_number', 'valuation_report_number', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'valuation_date', 'valuation_date', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'DATE'),
 ('valuation_report', 'valuation_valid_until', 'valuation_valid_until', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'DATE'),
 ('valuation_report', 'platform_name_as_printed', 'valuation_platform_name_printed', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'evaluator_name', 'valuation_evaluator_name', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'evaluator_employee_code', 'valuation_evaluator_employee_code', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'evaluator_signature_present', 'valuation_evaluator_signature_present', 'ORGANISATION', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'registration_number', 'vehicle_registration_number', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('valuation_report', 'chassis_number', 'chassis_number', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'IDENTIFIER'),
 ('valuation_report', 'make', 'vehicle_make', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('valuation_report', 'model', 'vehicle_model', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('valuation_report', 'variant', 'vehicle_variant', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('valuation_report', 'fuel_type', 'vehicle_fuel_type', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('valuation_report', 'manufacture_month_year', 'vehicle_manufacture_month_year', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'STRING'),
 ('valuation_report', 'registration_date', 'vehicle_registration_date', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'DATE'),
 ('valuation_report', 'odometer_km', 'vehicle_odometer_km', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'DECIMAL'),
 ('valuation_report', 'number_of_owners', 'vehicle_owner_count', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'INTEGER'),
 ('valuation_report', 'overall_grade', 'valuation_overall_grade', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'condition_parameters', 'valuation_condition_parameters', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'JSON'),
 ('valuation_report', 'accident_history_noted', 'vehicle_accident_history_noted', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'accident_remarks', 'vehicle_accident_remarks', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'flood_damage_noted', 'vehicle_flood_damage_noted', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'chassis_repair_noted', 'vehicle_chassis_repair_noted', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'tyres_condition', 'vehicle_tyres_condition', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'base_market_value', 'valuation_base_market_value', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'base_value_source_stated', 'valuation_base_value_source_stated', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'depreciation_applied', 'valuation_depreciation_applied', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'condition_deductions', 'valuation_condition_deductions', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'JSON'),
 ('valuation_report', 'total_deductions_stated', 'valuation_total_deductions_stated', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'additions', 'valuation_additions', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'JSON'),
 ('valuation_report', 'computed_fair_value_stated', 'valuation_computed_fair_value_stated', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'final_offer_value', 'valuation_final_offer_value', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'exchange_bonus_indicated_separately', 'valuation_exchange_bonus_separate', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'CURRENCY'),
 ('valuation_report', 'loan_outstanding_on_vehicle', 'exchange_vehicle_loan_outstanding', 'EXCHANGE_VEHICLE', 'EXTRACT_AND_COMPARE', 'CURRENCY'),
 ('valuation_report', 'photos_attached_count', 'valuation_photos_attached_count', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'INTEGER'),
 ('valuation_report', 'approval_name', 'valuation_approval_name', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'approval_designation', 'valuation_approval_designation', 'ORGANISATION', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'approval_signature_present', 'valuation_approval_signature_present', 'ORGANISATION', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'override_remark', 'valuation_override_remark', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'STRING'),
 ('valuation_report', 'customer_acceptance_signature', 'valuation_customer_acceptance_signature', 'CUSTOMER', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'offer_value_handwritten_or_amended', 'valuation_offer_value_handwritten_or_amended', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'BOOLEAN'),
 ('valuation_report', 'build_up_absent_only_final_figure_given', 'valuation_build_up_absent_only_final', 'EXCHANGE_VEHICLE', 'EVIDENCE', 'BOOLEAN'))

_STRUCTURED_RULES = {('gst_certificate', 'authorised_signatory_names'): {'container': 'array', 'item_type': 'string'},
 ('bank_approval_letter', 'conditions_precedent'): {'container': 'array', 'item_type': 'string'},
 ('valuation_report', 'condition_parameters'): {'container': 'array',
                                                 'item_type': 'object',
                                                 'properties': {'name': ['string', 'null'],
                                                                'score_as_printed': ['string', 'null'],
                                                                'is_blank': 'boolean'},
                                                 'required_keys': ['name', 'score_as_printed', 'is_blank'],
                                                 'allow_extra_keys': False},
 ('valuation_report', 'condition_deductions'): {'container': 'array',
                                                'item_type': 'object',
                                                'properties': {'head': ['string', 'null'],
                                                               'amount': ['number', 'null'],
                                                               'is_handwritten': 'boolean'},
                                                'required_keys': ['head', 'amount', 'is_handwritten'],
                                                'allow_extra_keys': False},
 ('valuation_report', 'additions'): {'container': 'array',
                                     'item_type': 'object',
                                     'properties': {'head': ['string', 'null'], 'amount': ['number', 'null']},
                                     'required_keys': ['head', 'amount'],
                                     'allow_extra_keys': False}}


def upgrade() -> None:
    bind = op.get_bind()

    # Deterministic rule catalogue used by the DRAFT profiles.
    for rule_key, description, implementation_key in (
        (
            "schema_v2.scalar_literal_parse",
            "Parse a provider scalar literal strictly as number, integer, or boolean.",
            "di.norm.scalar_literal_parse",
        ),
        (
            "schema_v2.date_iso8601",
            "Normalize unambiguous document dates to ISO-8601.",
            "di.norm.date_iso8601",
        ),
        (
            "schema_v2.structured_literal_parse",
            "Parse a provider array/object literal into typed JSON without silent row loss.",
            "di.norm.structured_literal_parse",
        ),
    ):
        bind.execute(
            sa.text("""
                INSERT INTO docintel.normalization_rule_catalog
                    (rule_key, description, implementation_key, parameter_schema, status)
                VALUES (:rk, :descr, :impl, NULL, 'ACTIVE')
                ON CONFLICT (rule_key) DO NOTHING
            """),
            {"rk": rule_key, "descr": description, "impl": implementation_key},
        )

    bind.execute(
        sa.text("""
            INSERT INTO docintel.validation_rule_catalog
                (rule_key, description, implementation_key, parameter_schema, result_scope, status)
            VALUES (
                'schema_v2.structured_shape',
                'Validate Schema V2 structured array/object shape without dropping malformed rows.',
                'di.val.structured_shape',
                NULL,
                'FIELD',
                'ACTIVE'
            )
            ON CONFLICT (rule_key) DO NOTHING
        """)
    )

    # Missing Wave-1 document types are catalogue entries only.  Existing rows are preserved.
    for key, display_name, physical_form in _DOCUMENT_TYPES:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.document_types (
                    document_type_id, owner_tenant_id, document_type_key,
                    display_name, description, category, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, :key, :display_name,
                       'Schema V2 Wave-1 document type', :physical_form, 'ACTIVE',
                       now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.document_types
                    WHERE owner_tenant_id IS NULL AND document_type_key=:key
                )
            """),
            {"key": key, "display_name": display_name, "physical_form": physical_form},
        )

    # Make the catalogue visible to existing tenants, but keep processing off while profiles are DRAFT.
    for key, _display_name, physical_form in _DOCUMENT_TYPES:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.tenant_document_types (
                    tenant_id, document_type_id, physical_form_type,
                    requires_processing, is_active, display_order,
                    created_at_utc, updated_at_utc
                )
                SELECT ts.tenant_id, dt.document_type_id, :physical_form,
                       false, true, 100, now(), now()
                FROM docintel.tenant_settings ts
                JOIN docintel.document_types dt
                  ON dt.owner_tenant_id IS NULL
                 AND dt.document_type_key=:key
                ON CONFLICT (tenant_id, document_type_id) DO NOTHING
            """),
            {"key": key, "physical_form": physical_form},
        )

    # Stable global canonical vocabulary. Existing canonical rows are never renamed or rewritten.
    for field_key, display_name, data_type in _CANONICAL_FIELDS:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.canonical_fields (
                    canonical_field_id, owner_tenant_id, field_key,
                    display_name, data_type, description, status,
                    created_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), NULL, :field_key,
                       :display_name, :data_type,
                       'Schema V2 Wave-1 canonical field', 'ACTIVE',
                       now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM docintel.canonical_fields
                    WHERE owner_tenant_id IS NULL AND field_key=:field_key
                )
            """),
            {"field_key": field_key, "display_name": display_name, "data_type": data_type},
        )

    # Create one isolated DRAFT profile per Wave-1 type. Never retire/publish an existing profile here.
    for key, _display_name, _physical_form in _DOCUMENT_TYPES:
        bind.execute(
            sa.text("""
                INSERT INTO docintel.extraction_profiles (
                    profile_id, document_type_id, scope_tenant_id, version_no,
                    profile_name, status, classification_hint,
                    created_by_actor_id, published_by_actor_id,
                    created_at_utc, published_at_utc, updated_at_utc
                )
                SELECT gen_random_uuid(), dt.document_type_id, NULL,
                       COALESCE((
                           SELECT MAX(ep2.version_no)
                           FROM docintel.extraction_profiles ep2
                           WHERE ep2.document_type_id=dt.document_type_id
                             AND ep2.scope_tenant_id IS NULL
                       ), 0) + 1,
                       :profile_name, 'DRAFT',
                       'Schema V2 Wave-1 draft. Not eligible for classification until explicitly published.',
                       'system.schema_v2', NULL, now(), NULL, now()
                FROM docintel.document_types dt
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key=:key
                  AND NOT EXISTS (
                      SELECT 1 FROM docintel.extraction_profiles ep
                      WHERE ep.document_type_id=dt.document_type_id
                        AND ep.scope_tenant_id IS NULL
                        AND ep.profile_name=:profile_name
                  )
            """),
            {"key": key, "profile_name": _PROFILE_NAME},
        )

    # Map provider-native extraction keys onto the stable canonical vocabulary + fact role.
    for seq, (dt_key, extraction_key, canonical_key, fact_role, _source_class, canonical_type) in enumerate(_PROFILE_FIELDS, 1):
        profile_id = bind.execute(
            sa.text("""
                SELECT ep.profile_id
                FROM docintel.extraction_profiles ep
                JOIN docintel.document_types dt ON dt.document_type_id=ep.document_type_id
                WHERE dt.owner_tenant_id IS NULL
                  AND dt.document_type_key=:dt_key
                  AND ep.scope_tenant_id IS NULL
                  AND ep.profile_name=:profile_name
                  AND ep.status='DRAFT'
                ORDER BY ep.version_no DESC
                LIMIT 1
            """),
            {"dt_key": dt_key, "profile_name": _PROFILE_NAME},
        ).scalar_one()

        canonical_id = bind.execute(
            sa.text("""
                SELECT canonical_field_id
                FROM docintel.canonical_fields
                WHERE owner_tenant_id IS NULL AND field_key=:canonical_key
            """),
            {"canonical_key": canonical_key},
        ).scalar_one()

        bind.execute(
            sa.text("""
                INSERT INTO docintel.extraction_profile_fields (
                    profile_field_id, profile_id, canonical_field_id,
                    enabled, expected, extraction_instruction, aliases,
                    score_included, score_weight,
                    use_for_subject_matching, subject_identifier_type,
                    manual_correction_allowed, display_sequence,
                    created_at_utc, updated_at_utc,
                    extraction_key, fact_role_override
                )
                SELECT gen_random_uuid(), :profile_id, :canonical_id,
                       true, false, NULL, CAST('[]' AS jsonb),
                       false, 1.0,
                       false, NULL,
                       true, :display_sequence,
                       now(), now(),
                       :extraction_key, :fact_role
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM docintel.extraction_profile_fields epf
                    WHERE epf.profile_id=:profile_id
                      AND epf.extraction_key=:extraction_key
                )
            """),
            {
                "profile_id": profile_id,
                "canonical_id": canonical_id,
                "display_sequence": seq,
                "extraction_key": extraction_key,
                "fact_role": fact_role,
            },
        )

        profile_field_id = bind.execute(
            sa.text("""
                SELECT profile_field_id
                FROM docintel.extraction_profile_fields
                WHERE profile_id=:profile_id AND extraction_key=:extraction_key
            """),
            {"profile_id": profile_id, "extraction_key": extraction_key},
        ).scalar_one()

        # Provider output is text at the rules boundary, so recover strict typed scalars deterministically.
        scalar_type = None
        if canonical_type in ("CURRENCY", "DECIMAL"):
            scalar_type = "number"
        elif canonical_type == "INTEGER":
            scalar_type = "integer"
        elif canonical_type == "BOOLEAN":
            scalar_type = "boolean"

        normalizer = None
        parameters = None
        if (dt_key, extraction_key) in _STRUCTURED_RULES:
            normalizer = "schema_v2.structured_literal_parse"
            parameters = {"container": _STRUCTURED_RULES[(dt_key, extraction_key)]["container"]}
        elif scalar_type is not None:
            normalizer = "schema_v2.scalar_literal_parse"
            parameters = {"type": scalar_type}
        elif canonical_type == "DATE":
            normalizer = "schema_v2.date_iso8601"
            parameters = {"locale": "iso"}

        if normalizer is not None:
            bind.execute(
                sa.text("""
                    INSERT INTO docintel.profile_field_normalizers (
                        profile_field_normalizer_id, profile_field_id,
                        sequence_no, rule_key, parameters
                    )
                    SELECT gen_random_uuid(), :pfid, 1, :rule_key, CAST(:params AS jsonb)
                    WHERE NOT EXISTS (
                        SELECT 1 FROM docintel.profile_field_normalizers pfn
                        WHERE pfn.profile_field_id=:pfid AND pfn.sequence_no=1
                    )
                """),
                {
                    "pfid": profile_field_id,
                    "rule_key": normalizer,
                    "params": json.dumps(parameters),
                },
            )

        structured_params = _STRUCTURED_RULES.get((dt_key, extraction_key))
        if structured_params is not None:
            bind.execute(
                sa.text("""
                    INSERT INTO docintel.profile_field_validators (
                        profile_field_validator_id, profile_field_id,
                        sequence_no, rule_key, parameters, severity
                    )
                    SELECT gen_random_uuid(), :pfid, 1,
                           'schema_v2.structured_shape', CAST(:params AS jsonb), 'ERROR'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM docintel.profile_field_validators pfv
                        WHERE pfv.profile_field_id=:pfid AND pfv.sequence_no=1
                    )
                """),
                {"pfid": profile_field_id, "params": json.dumps(structured_params)},
            )


def downgrade() -> None:
    # Configuration is intentionally not destructively removed because canonical
    # vocabulary may already be referenced by immutable facts.  Reject/discard the
    # Schema V2 sandbox branch if this experiment is not promoted.
    pass
