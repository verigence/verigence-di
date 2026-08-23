from __future__ import annotations

from starlette.requests import Request

from verigence.di.auth import human_admin


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "scheme": "https",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 443),
        }
    )


def test_project_master_catalog_template_and_versions_are_lightweight_reads() -> None:
    for path in (
        "/v1/tenants/t-1/project-masters",
        "/v1/tenants/t-1/project-masters/DOCUMENT_TYPES/template",
        "/v1/tenants/t-1/project-masters/DOCUMENT_TYPES/versions",
    ):
        assert human_admin._is_lightweight_master_read(_request("GET", path))


def test_master_mutations_and_import_details_stay_on_admin_boundary() -> None:
    assert not human_admin._is_lightweight_master_read(
        _request("POST", "/v1/tenants/t-1/project-masters/DOCUMENT_TYPES/imports")
    )
    assert not human_admin._is_lightweight_master_read(
        _request("GET", "/v1/tenants/t-1/project-masters/DOCUMENT_TYPES/imports/i-1")
    )
    assert not human_admin._is_lightweight_master_read(
        _request("GET", "/v1/tenants/t-1/project-masters/DOCUMENT_TYPES/imports/i-1/error-report")
    )
