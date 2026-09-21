"""RTO Challan extraction schema for UC03 final-report evidence."""
from __future__ import annotations

from verigence.di.document_ai.schemas.base import FieldSpec, SchemaDefinition

RTO_CHALLAN_SCHEMA = SchemaDefinition(
    document_type_key="rto_challan",
    display_name="RTO Challan",
    schema_version="2.0",
    fields=[
        FieldSpec(
            "registration_number",
            "string",
            False,
            "Vehicle registration number only when explicitly printed or labelled on the RTO paper/challan.",
        ),
        FieldSpec(
            "registration_state",
            "string",
            False,
            "Registration/RTO State only when explicitly printed; never infer it from the registration number or RTO code.",
        ),
        FieldSpec(
            "registration_territory",
            "string",
            False,
            "Registration Territory/UT only when explicitly printed; never derive it from State, registration number, RTO code, or geography knowledge.",
        ),
        FieldSpec(
            "registration_district",
            "string",
            False,
            "Registration/RTO district only when explicitly printed; never infer it from an RTO code, city, State, or geography knowledge.",
        ),
        FieldSpec(
            "ex_showroom_amount",
            "number",
            False,
            "Ex-showroom amount only when explicitly labelled and printed; never calculate it from totals, taxes, fees, or another amount.",
        ),
        FieldSpec(
            "registration_type",
            "string",
            False,
            "Registration type/category exactly as printed; never classify or infer it from vehicle, customer, finance, or tax context.",
        ),
        FieldSpec(
            "hp_charges_amount",
            "number",
            False,
            "Hypothecation/HP charges only when explicitly labelled and printed; never derive or calculate them from finance details.",
        ),
        FieldSpec(
            "chassis_number",
            "string",
            False,
            "Vehicle chassis number exactly as printed; never derive it from a registration number or VIN.",
        ),
        FieldSpec(
            "financer_name",
            "string",
            False,
            "Financer/bank name exactly as printed (e.g. against 'FinancerName' or 'Financed By'); null when the document shows no financer.",
        ),
        FieldSpec(
            "bank_reference_number",
            "string",
            False,
            "Bank reference number exactly as printed (e.g. against 'Bank Ref No').",
        ),
        FieldSpec(
            "receipt_number",
            "string",
            False,
            "Receipt/application number exactly as printed (e.g. against 'RECEIPT/APPL No'), preserved verbatim including any slash-separated parts.",
        ),
        FieldSpec(
            "receipt_date",
            "date",
            False,
            "Receipt date exactly as printed; never confuse it with a separate 'Printed On' timestamp.",
        ),
        FieldSpec(
            "grand_total_amount",
            "number",
            False,
            "Final grand total amount exactly as printed; never recompute it by summing the Particulars table.",
        ),
        FieldSpec(
            "line_items",
            "array",
            False,
            (
                "JSON array with ONE ENTRY PER PRINTED ROW of the Particulars/charges table -- "
                "an RTO Challan's fee break-up routinely lists many separate rows (for example: "
                "Registration Fee, Road Tax, Hypothecation/HPA Charges, Smart Card Fee, Fitness "
                "Fee, Fancy/Choice Number Fee, Form Fee, Postal/Speed Post Charges, Agent Fee, "
                "Cess), each with its own amount -- return every one of them as its own array "
                "element, never a single summarized or totaled entry. Scan the ENTIRE table from "
                "its first printed row to its last before answering; a table with N printed rows "
                "must produce an array of exactly N items, never fewer. For each row preserve "
                "description_raw exactly as printed, and extract only explicitly printed amount, "
                "rebate_waiver_amount, fine_penalty_amount and total. Never merge two or more "
                "printed rows into one array element, never invent a row that is not printed, and "
                "never collapse the table down to only its total/grand-total row."
            ),
        ),
    ],
    system_prompt=(
        "You extract final-report evidence from an automobile RTO Challan or RTO paper. "
        "Return only values explicitly visible on the document. Never decode registration "
        "numbers or RTO codes into geography, and never derive monetary values."
    ),
    prompt_notes=[
        "Preserve printed registration and geography text; do not use outside geography knowledge.",
        "If State, Territory/UT, or District is not explicitly identifiable, return null for that field.",
        "Return ex_showroom_amount and hp_charges_amount only from explicitly labelled printed amounts.",
        "Return registration_type only from explicit source text; do not classify it yourself.",
        "Extract chassis_number and financer_name exactly as printed; do not derive either from other document fields.",
        "line_items is almost never a single row in practice -- an RTO Challan's Particulars/fee "
        "table typically prints 5 to 15 separate charge lines. Before finalizing line_items, "
        "re-count the printed rows in the table image and confirm the array has that same number "
        "of elements; a one-element array is correct ONLY if the printed table itself genuinely "
        "shows just one row. Do not merge separate printed Particulars rows into one, and do not "
        "compute grand_total_amount yourself -- extract it only if explicitly printed.",
    ],
)
