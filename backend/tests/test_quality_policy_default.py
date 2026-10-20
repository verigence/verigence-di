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
        "di.quality.image_contrast",
        "di.quality.pdf_page_count",
    ]
    for entry in DEFAULT_QUALITY_POLICY:
        assert entry["rule_key"] in catalogued and entry["enabled"] is True
    by_key = {p["rule_key"]: p["parameters"] for p in DEFAULT_QUALITY_POLICY}
    assert by_key["di.quality.image_min_dimensions"] == {"min_width": 800, "min_height": 600}
    assert by_key["di.quality.image_blur_score"] == {"min_variance": 80.0}
    assert by_key["di.quality.pdf_page_count"] == {"max_pages": 100}
    assert by_key["di.quality.image_contrast"] == {"max_ink_level": 90.0, "min_stroke_contrast": 160.0}


def _load(name: str):
    path = _MIGRATION.parent / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_tenants_and_the_migrations_use_the_same_policy() -> None:
    """0049 gave every tenant the policy of its day; 0053 adds the contrast
    rule. Together they are today's default, and so are new tenants'."""
    assert json.loads(tenants._DEFAULT_QUALITY_POLICY) == DEFAULT_QUALITY_POLICY
    migration = _migration()
    contrast = _load("0053_quality_contrast_rule.py")
    migrated = [*migration._DEFAULT_POLICY, contrast._POLICY_ENTRY]
    key = lambda rule: rule["rule_key"]  # noqa: E731
    assert sorted(migrated, key=key) == sorted(DEFAULT_QUALITY_POLICY, key=key)
    catalogued = [(r[0], r[1]) for r in migration._CATALOG] + [(contrast._RULE_KEY, contrast._RULE_KEY)]
    assert sorted(catalogued) == sorted(
        (c["rule_key"], c["implementation_key"]) for c in QUALITY_RULE_CATALOG
    )
    by_key = {c["rule_key"]: c for c in QUALITY_RULE_CATALOG}
    assert by_key[contrast._RULE_KEY]["description"] == contrast._DESCRIPTION
    assert by_key[contrast._RULE_KEY]["parameter_schema"] == contrast._SCHEMA


def test_a_quality_rejection_code_is_what_audit_core_expects() -> None:
    # validator.py: upload_issue_code = rule_key.upper().replace(".", "_")
    for entry in DEFAULT_QUALITY_POLICY:
        assert entry["rule_key"].upper().replace(".", "_").startswith("DI_QUALITY_")
