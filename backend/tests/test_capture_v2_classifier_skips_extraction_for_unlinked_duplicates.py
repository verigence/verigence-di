"""tests/test_capture_v2_classifier_skips_extraction_for_unlinked_duplicates.py

Source-inspection guard: a classified document with no requirement_ref
(Audit Core's _requirements_with_open_slot omits one for an extra copy of a
single-document requirement that's already fulfilled) must never reach
create_initial_job -- extraction is real DI compute spent on data nothing
will ever read. Classification itself is unconditional and must still
happen either way; this only gates the extraction step that follows it.
"""
from __future__ import annotations

import inspect

import pytest

from verigence.di.workers import capture_v2_classifier


@pytest.mark.no_docker
def test_create_initial_job_is_gated_on_requirement_ref_not_none() -> None:
    # The gate is extraction_skip_reason: queued only when it returns None,
    # and it returns a reason whenever requirement_ref is None.
    source = inspect.getsource(capture_v2_classifier)
    start = source.index("requirement_ref = requirement_map.get(accepted)")
    call_site = source.index("create_initial_job(", start)
    guard = source.rindex("if ", start, call_site)
    condition = source[guard:call_site]
    assert "skipped_reason is None" in condition
    decision = source[source.index("skipped_reason = extraction_skip_reason(", start):guard]
    assert "requirement_ref=requirement_ref" in decision
    assert "requires_processing" in decision
    assert "has_published_profile" in decision
    assert capture_v2_classifier.extraction_skip_reason(
        requirement_ref=None, requires_processing=True, has_published_profile=True,
    ) is not None
