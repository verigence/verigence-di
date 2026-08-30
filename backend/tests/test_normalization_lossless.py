from verigence.di.rules.runner import _run_normalizers


def test_missing_normalizer_does_not_erase_extracted_value() -> None:
    raw = "VALUE EXTRACTED BY PROVIDER"
    result = _run_normalizers(
        raw,
        [{"implementation_key": "normalizer_that_does_not_exist", "parameters": {}}],
    )

    assert result.ok is False
    assert result.normalized_value == raw
    assert "not registered" in (result.message or "")


def test_null_raw_stays_null_on_normalization_failure() -> None:
    result = _run_normalizers(
        None,
        [{"implementation_key": "normalizer_that_does_not_exist", "parameters": {}}],
    )

    assert result.ok is False
    assert result.normalized_value is None


def test_no_normalizer_preserves_raw_value() -> None:
    raw = "₹ 50,000"
    result = _run_normalizers(raw, [])

    assert result.ok is True
    assert result.normalized_value == raw
