from verigence.di.document_ai.uc03_booking_profile import filter_uc03_booking_result


def test_review_business_fields_are_not_silently_dropped() -> None:
    extracted = {
        "customer_email": {"value": "customer@example.com"},
        "dealer_name": {"value": "Dealer A"},
        "ex_showroom_price": {"value": 1000000},
        "road_tax_registration": {"value": 80000},
        "insurance_amount": {"value": 50000},
        "accessories_cost": {"value": 15000},
        "additional_warranty_amount": {"value": 12000},
        "balance_amount": {"value": 1065000},
        "bonus_amount": {"value": 10000},
        "mode_of_payment": {"value": "CARD"},
        "payment_reference_no": {"value": "PAY123"},
        "discount_amount": {"value": 25000},
        "exchange_applicable": {"value": True},
        "exchange_value": {"value": 300000},
    }

    assert filter_uc03_booking_result("booking_form", extracted) == extracted
