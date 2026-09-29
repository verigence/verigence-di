"""Every tenant starts with the default scan-quality policy; the policy and
the migration's catalogue name only rules that exist in the registry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from verigence.di.quality.policy import DEFAULT_QUALITY_POLICY, QUALITY_RULE_CATALOG
from verigence.di.quality.rules import REGISTRY
from verigence.di.repositories import tenants

pytestmark = pytest.mark.no_docker

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0049_quality_catalog_and_default_policy.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0049", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogue_covers_every_registered_rule_and_nothing_else() -> None:
    assert {c["implementation_key"] for c in QUALITY_RULE_CATALOG} == set(REGISTRY)
    assert {c["rule_key"] for c in QUALITY_RULE_CATALOG} == {
        c["implementation_key"] for c in QUALITY_RULE_CATALOG
    }


def test_default_policy_names_catalogued_rules_with_their_parameters() -> None:
    catalogued = {c["rule_key"] for c in QUALITY_RULE_CATALOG}
    assert [p["rule_key"] for p in DEFAULT_QUALITY_POLICY] == [
        "di.quality.file_not_empty",
        "di.quality.image_min_dimensions",
        "di.quality.image_blur_score",
        "di.quality.pdf_page_count",
    ]
    for entry in DEFAULT_QUALITY_POLICY:
        assert entry["rule_key"] in catalogued and entry["enabled"] is True
    by_key = {p["rule_key"]: p["parameters"] for p in DEFAULT_QUALITY_POLICY}
    assert by_key["di.quality.image_min_dimensions"] == {"min_width": 800, "min_height": 600}
    assert by_key["di.quality.image_blur_score"] == {"min_variance": 80.0}
    assert by_key["di.quality.pdf_page_count"] == {"max_pages": 100}


def test_new_tenants_and_the_migration_use_the_same_policy() -> None:
    assert json.loads(tenants._DEFAULT_QUALITY_POLICY) == DEFAULT_QUALITY_POLICY
    migration = _migration()
    assert migration._DEFAULT_POLICY == DEFAULT_QUALITY_POLICY
    assert [(r[0], r[1]) for r in migration._CATALOG] == [
        (c["rule_key"], c["implementation_key"]) for c in QUALITY_RULE_CATALOG
    ]


def test_a_quality_rejection_code_is_what_audit_core_expects() -> None:
    # validator.py: upload_issue_code = rule_key.upper().replace(".", "_")
    for entry in DEFAULT_QUALITY_POLICY:
        assert entry["rule_key"].upper().replace(".", "_").startswith("DI_QUALITY_")
