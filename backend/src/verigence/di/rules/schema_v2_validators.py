"""Schema V2 deterministic validators for structured extraction values.

Kept separate from the legacy validator module so Schema V2 can add typed JSON
row validation without changing historical validator implementations.  The rules
runner consults this registry only when the legacy registry has no matching key.
"""
from __future__ import annotations

from typing import Any, Callable

from verigence.di.rules.validators import ValidatorRuleResult

SchemaV2ValidatorFn = Callable[[Any, str | None, dict[str, Any]], ValidatorRuleResult]


def _result(
    result: str,
    severity: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> ValidatorRuleResult:
    return ValidatorRuleResult(
        rule_key="schema_v2.structured_shape",
        result=result,
        severity=severity,
        message=message,
        details=details,
    )


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "null":
        return value is None
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    return False


def _allowed_types(spec: Any) -> list[str]:
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, list) and all(isinstance(item, str) for item in spec):
        return list(spec)
    return []


def _validate_value(value: Any, spec: Any, *, path: str) -> list[str]:
    allowed = _allowed_types(spec)
    if not allowed:
        return [f"{path}: validator configuration has no valid type specification"]
    if any(_matches_type(value, type_name) for type_name in allowed):
        return []
    return [
        f"{path}: expected {'|'.join(allowed)}, got {type(value).__name__}"
    ]


def _validate_object_row(
    row: Any,
    *,
    row_index: int,
    properties: dict[str, Any],
    required_keys: list[str],
    allow_extra_keys: bool,
) -> list[str]:
    path = f"$[{row_index}]"
    if not isinstance(row, dict):
        return [f"{path}: expected object, got {type(row).__name__}"]

    errors: list[str] = []
    for key in required_keys:
        if key not in row:
            errors.append(f"{path}.{key}: required key is missing")

    if not allow_extra_keys:
        extras = sorted(set(row) - set(properties))
        for key in extras:
            errors.append(f"{path}.{key}: unexpected key")

    for key, type_spec in properties.items():
        if key not in row:
            continue
        errors.extend(_validate_value(row[key], type_spec, path=f"{path}.{key}"))
    return errors


def _validate_structured_shape(
    value: Any,
    raw: str | None,
    params: dict[str, Any],
) -> ValidatorRuleResult:
    """Validate a JSON array and, optionally, a deterministic row schema.

    Parameters are profile-owned configuration and therefore versioned with the
    extraction profile.  Supported form::

        {
          "container": "array",
          "item_type": "string" | "object",
          "properties": {"head": ["string", "null"], ...},
          "required_keys": ["head", ...],
          "allow_extra_keys": false,
          "min_items": 0
        }

    No row is repaired or dropped.  Every shape error is reported with a JSON-ish
    path so the document can route to review with the original extracted value.
    """
    del raw
    severity = str(params.get("severity", "ERROR"))
    if value is None:
        return _result("SKIP", severity, "No structured value to validate")

    container = params.get("container", "array")
    if container != "array":
        return _result(
            "ERROR",
            "ERROR",
            f"Unsupported structured container {container!r}",
        )
    if not isinstance(value, list):
        return _result(
            "FAIL",
            severity,
            f"Expected array, got {type(value).__name__}",
            {"error_paths": ["$"]},
        )

    min_items = int(params.get("min_items", 0))
    if len(value) < min_items:
        return _result(
            "FAIL",
            severity,
            f"Expected at least {min_items} rows, got {len(value)}",
            {"row_count": len(value), "min_items": min_items, "error_paths": ["$"]},
        )

    item_type = params.get("item_type", "object")
    errors: list[str] = []

    if item_type == "string":
        for index, item in enumerate(value):
            errors.extend(_validate_value(item, "string", path=f"$[{index}]"))
    elif item_type == "object":
        properties = params.get("properties") or {}
        required_keys = params.get("required_keys") or []
        allow_extra_keys = bool(params.get("allow_extra_keys", False))
        if not isinstance(properties, dict):
            return _result("ERROR", "ERROR", "properties must be an object")
        if not isinstance(required_keys, list) or not all(
            isinstance(key, str) for key in required_keys
        ):
            return _result("ERROR", "ERROR", "required_keys must be an array of strings")
        for index, row in enumerate(value):
            errors.extend(
                _validate_object_row(
                    row,
                    row_index=index,
                    properties=properties,
                    required_keys=required_keys,
                    allow_extra_keys=allow_extra_keys,
                )
            )
    else:
        return _result(
            "ERROR",
            "ERROR",
            f"Unsupported item_type {item_type!r}",
        )

    if errors:
        return _result(
            "FAIL",
            severity,
            f"Structured value has {len(errors)} shape error(s)",
            {
                "row_count": len(value),
                "errors": errors,
                "error_paths": [error.split(":", 1)[0] for error in errors],
            },
        )

    return _result(
        "PASS",
        severity,
        details={"row_count": len(value)},
    )


SCHEMA_V2_VALIDATOR_REGISTRY: dict[str, SchemaV2ValidatorFn] = {
    "di.val.structured_shape": _validate_structured_shape,
}


def get_schema_v2_validator(implementation_key: str) -> SchemaV2ValidatorFn | None:
    return SCHEMA_V2_VALIDATOR_REGISTRY.get(implementation_key)
