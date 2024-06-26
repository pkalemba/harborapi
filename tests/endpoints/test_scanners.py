from __future__ import annotations

import pytest
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from pytest_httpserver import HTTPServer

from harborapi.client import HarborAsyncClient
from harborapi.exceptions import HarborAPIException
from harborapi.models import IsDefault
from harborapi.models import ScannerAdapterMetadata
from harborapi.models import ScannerRegistration
from harborapi.models import ScannerRegistrationReq
from harborapi.models import ScannerRegistrationSettings


@pytest.mark.asyncio
@given(st.builds(ScannerRegistrationReq))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_create_scanner_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner: ScannerRegistrationReq,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners", method="POST"
    ).respond_with_data(status=201, headers={"Location": "/scanners/1234"})

    resp = await async_client.create_scanner(scanner)
    assert resp == "/scanners/1234"


@pytest.mark.asyncio
@given(st.builds(ScannerRegistration), st.builds(ScannerRegistration))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_scanners_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner1: ScannerRegistration,
    scanner2: ScannerRegistration,
):
    # TODO: use st.lists(st.builds(ScannerRegistration)) to generate a list of scanners
    httpserver.expect_oneshot_request("/api/v2.0/scanners").respond_with_json(
        [scanner1.model_dump(), scanner2.model_dump()]
    )

    resp = await async_client.get_scanners()
    assert len(resp) == 2
    assert resp[0].model_dump() == scanner1.model_dump()
    assert resp[1].model_dump() == scanner2.model_dump()


@pytest.mark.asyncio
@given(st.builds(ScannerRegistration))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_scanner_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner: ScannerRegistration,
):
    httpserver.expect_oneshot_request("/api/v2.0/scanners/1234").respond_with_json(
        scanner.model_dump()
    )

    resp = await async_client.get_scanner(registration_id=1234)
    assert resp.model_dump() == scanner.model_dump()


@pytest.mark.asyncio
@given(st.builds(ScannerAdapterMetadata))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_get_scanner_metadata_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scannermeta: ScannerAdapterMetadata,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/1234/metadata"
    ).respond_with_json(scannermeta.model_dump(mode="json", exclude_unset=True))

    resp = await async_client.get_scanner_metadata(registration_id=1234)
    assert resp == scannermeta


@pytest.mark.asyncio
@given(st.builds(ScannerRegistration))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_delete_scanner_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner: ScannerRegistration,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/1234", method="DELETE"
    ).respond_with_data(scanner.model_dump_json(), content_type="application/json")

    resp = await async_client.delete_scanner(1234)
    assert resp.model_dump() == scanner.model_dump()


@pytest.mark.asyncio
@given(st.builds(ScannerRegistration))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_delete_scanner_no_response_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner: ScannerRegistration,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/1234", method="DELETE"
    ).respond_with_data("{}", content_type="application/json")

    with pytest.raises(HarborAPIException) as exc_info:
        await async_client.delete_scanner(1234)
    assert "got nothing" in exc_info.value.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_default",
    [True, False],
)
async def test_set_default_scanner_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    is_default: bool,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/1234",
        method="PATCH",
        json=IsDefault(is_default=is_default).model_dump(
            mode="json", exclude_unset=True
        ),
    ).respond_with_data()

    await async_client.set_default_scanner(1234, is_default)


@pytest.mark.asyncio
@given(st.builds(ScannerRegistrationSettings))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_ping_scanner_adapter_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    settings: ScannerRegistrationSettings,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/ping",
        method="POST",
        json=settings.model_dump(mode="json", exclude_unset=True),
    ).respond_with_data()

    await async_client.ping_scanner_adapter(settings)


@pytest.mark.asyncio
@given(st.builds(ScannerRegistrationReq))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_update_scanner_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    scanner: ScannerRegistrationReq,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/scanners/1234",
        method="PUT",
        json=scanner.model_dump(mode="json", exclude_unset=True),
    ).respond_with_data()

    await async_client.update_scanner(1234, scanner)
