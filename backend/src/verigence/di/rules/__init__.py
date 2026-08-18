"""rules/ — Deterministic normalization + validation rule package.

Public surface for the Processing Worker (DI_LLD_v2.2 §Processing Worker steps 11–12).

Normalization (step 11):
    Apply ordered profile_field_normalizers per field.
    10 built-in rules in normalizers.NORMALIZER_REGISTRY.

Validation (step 12):
    Apply ordered profile_field_validators per field.
    Persist validation_results rows.
    11 built-in rules in validators.VALIDATOR_REGISTRY.

Primary entry point:
    from verigence.di.rules.runner import normalize_and_validate
"""
from verigence.di.rules.normalizers import (
    NORMALIZER_REGISTRY,
    NormalizerResult,
    get_normalizer,
)
from verigence.di.rules.runner import (
    ExtractedFieldInput,
    FieldValidationOutput,
    NormalizedFieldOutput,
    RunnerOutput,
    normalize_and_validate,
)
from verigence.di.rules.validators import (
    VALIDATOR_REGISTRY,
    ValidatorRuleResult,
    get_validator,
)

__all__ = [
    # normalizers
    "NORMALIZER_REGISTRY",
    "NormalizerResult",
    "get_normalizer",
    # validators
    "VALIDATOR_REGISTRY",
    "ValidatorRuleResult",
    "get_validator",
    # runner
    "ExtractedFieldInput",
    "FieldValidationOutput",
    "NormalizedFieldOutput",
    "RunnerOutput",
    "normalize_and_validate",
]
