# DI schema snapshot before generalized invoice intelligence

Snapshot date: 2026-08-30
Base branch: `dev`
Base commit: `6563a9e9d73108bc2141bcbf21a197e36ce8f441`
Feature branch: `feature/generalized-invoice-intelligence`

This directory is an explicit pre-change rollback reference. The base commit above contains the complete immutable pre-change repository tree. Existing document schemas are not to be rewritten by the invoice generalization; the change is additive except for the registry/classifier wiring copied below.

## Current schema files at base commit

- `schemas/__init__.py` — `13705e01bfb19c95411ad96d099bd53db210999a`
- `schemas/_fallback.py` — `ef0495c172b6cf4f1d875ce248b0aea6463ee7c7`
- `schemas/aadhaar.py` — `88db3622224cef1c5f62377c1d1d558111329601`
- `schemas/bank_approval_letter.py` — `550d4ed0db8ecfed1d537b0c5d581fe3366e89c0`
- `schemas/bank_statement.py` — `aa2f28eef242a7ec2b5a2c1c3402fe24811d7f00`
- `schemas/base.py` — `d8d67f82bc694af622db56a9d9130691994dde5f`
- `schemas/booking_form.py` — `1491ab6bb952c34eb54497c3ea434114511de03c`
- `schemas/corporate_id.py` — `19070476db026b1022f5398a08ea32f0314881aa`
- `schemas/dealer_receipt.py` — `7f5f91e8c28137b4c53aa5df1542d69522a29431`
- `schemas/delivery_order.py` — `34de762bf13bf32add6effb7596fb83150ad6948`
- `schemas/gst_certificate.py` — `cc90d84a42916566c2ff8d98852a21ad9896d179`
- `schemas/insurance_cover.py` — `bf034b388a7cce9dc1cac45b17cda16d74296fbc`
- `schemas/pan_card.py` — `ff96f55e46008abd2adcab072349b1451f41bf75`
- `schemas/upi_screenshot.py` — `3c4c58f6d7c5b94a5c1c612a23abe28aeeef62b1`
- `schemas/upi_transaction.py` — `b2a3fabde852fd62c76c2c703240a6d35b69908f`
- `schemas/valuation_report.py` — `697d11d8f1c6aa6001b1492fe374f5233e9da6fc`

## Runtime files copied verbatim in this backup

- `backend/src/verigence/di/document_ai/schemas/__init__.py`
- `backend/src/verigence/di/document_ai/schemas/base.py`
- `backend/src/verigence/di/document_ai/v2_classifier.py`

## Rollback

Preferred rollback is a Git revert of the generalized-invoice PR. If a file-level restore is needed, restore registry/classifier from this backup or from base commit `6563a9e9d73108bc2141bcbf21a197e36ce8f441`. Historical extraction profiles/evidence must never be deleted; rollback of profile activation is done by publishing/re-activating the previous profile state rather than deleting evidence.
