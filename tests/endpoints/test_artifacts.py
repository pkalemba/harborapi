from contextlib import nullcontext
from typing import List

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pytest_httpserver import HTTPServer

from harborapi.client import HarborAsyncClient
from harborapi.exceptions import StatusError
from harborapi.models import HarborVulnerabilityReport
from harborapi.models.models import Accessory, Artifact, Tag

from ..strategies.artifact import get_hbv_strategy


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 201])
@given(st.builds(Tag))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_create_artifact_tag_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
    tag: Tag,
):
    async_client.url = httpserver.url_for("/api/v2.0")
    expect_location = (
        async_client.url
        + "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/tags/123"
    )
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/tags",
        method="POST",
        json=tag.dict(),
    ).respond_with_data(
        headers={"Location": expect_location},
        status=status_code,
    )
    location = await async_client.create_artifact_tag(
        "testproj", "testrepo", "latest", tag
    )
    assert location == expect_location
    if status_code == 200:
        assert "expected 201" in caplog.text


@pytest.mark.asyncio
@given(get_hbv_strategy())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_artifact_vulnerabilities_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    report: HarborVulnerabilityReport,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/additions/vulnerabilities",
        method="GET",
    ).respond_with_data(
        # use report.json() to avoid datetime serialization issues
        '{{"application/vnd.security.vulnerability.report; version=1.1": {r}}}'.format(
            r=report.json()
        ),
        headers={"Content-Type": "application/json"},
    )
    async_client.url = httpserver.url_for("/api/v2.0")
    r = await async_client.get_artifact_vulnerabilities(
        "testproj", "testrepo", "latest"
    )
    # TODO: add test for empty response ('{}')
    # TODO: specify MIME type when testing?
    assert r == report


@pytest.mark.asyncio
async def test_get_artifact_vulnerabilities_empty_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
):
    """Tests that an empty response is handled correctly.

    Empty responses can occur when the server does not have a report for
    the given MIME type.
    """
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/additions/vulnerabilities",
        method="GET",
    ).respond_with_json({})

    async_client.url = httpserver.url_for("/api/v2.0")
    r = await async_client.get_artifact_vulnerabilities(
        "testproj", "testrepo", "latest"
    )
    assert r == None


@pytest.mark.asyncio
@given(st.lists(st.builds(Tag)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_artifact_tags_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    tags: List[Tag],
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/tags",
        method="GET",
    ).respond_with_data(
        "[" + ",".join(t.json() for t in tags) + "]",
        headers={"Content-Type": "application/json"},
    )
    async_client.url = httpserver.url_for("/api/v2.0")
    tags_resp = await async_client.get_artifact_tags("testproj", "testrepo", "latest")
    # TODO: test params
    assert tags_resp == tags
    for tag in tags_resp:
        assert isinstance(tag, Tag)


@pytest.mark.asyncio
@given(st.lists(st.builds(Accessory)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_artifact_accessories_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    accessories: List[Accessory],
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/accessories",
        method="GET",
    ).respond_with_data(
        "[" + ",".join(a.json() for a in accessories) + "]",
        headers={"Content-Type": "application/json"},
    )
    async_client.url = httpserver.url_for("/api/v2.0")
    accessories_resp = await async_client.get_artifact_accessories(
        "testproj", "testrepo", "latest"
    )
    assert accessories_resp == accessories
    for accessory in accessories_resp:
        assert isinstance(accessory, Accessory)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 404])
@pytest.mark.parametrize("missing_ok", [True, False])
async def test_delete_artifact_tag(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    status_code: int,
    missing_ok: bool,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts/latest/tags/123",
        method="DELETE",
    ).respond_with_data(status=status_code)
    async_client.url = httpserver.url_for("/api/v2.0")
    if status_code == 404 and not missing_ok:
        ctx = pytest.raises(StatusError)
    else:
        ctx = nullcontext()  # type: ignore
    with ctx:
        await async_client.delete_artifact_tag(
            "testproj", "testrepo", "latest", "123", missing_ok=missing_ok
        )


@pytest.mark.asyncio
async def test_copy_artifact(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts",
        query_string={"from": "oldproj/oldrepo:oldtag"},
        method="POST",
    ).respond_with_data(status=201, headers={"Location": "/api/v2.0/artifacts/123"})
    async_client.url = httpserver.url_for("/api/v2.0")

    location = await async_client.copy_artifact(
        "testproj",
        "testrepo",
        "oldproj/oldrepo:oldtag",
    )
    assert location == "/api/v2.0/artifacts/123"


@pytest.mark.asyncio
@given(st.lists(st.builds(Artifact)))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_artifacts_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    artifacts: List[Artifact],
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/projects/testproj/repositories/testrepo/artifacts",
        method="GET",
    ).respond_with_data(
        "[" + ",".join(a.json() for a in artifacts) + "]",
        headers={"Content-Type": "application/json"},
    )
    async_client.url = httpserver.url_for("/api/v2.0")
    accessories_resp = await async_client.get_artifacts(
        "testproj",
        "testrepo",
    )
    # TODO: add params tests
    assert accessories_resp == artifacts
    for accessory in accessories_resp:
        assert isinstance(accessory, Artifact)