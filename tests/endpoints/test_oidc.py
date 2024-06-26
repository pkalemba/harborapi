from __future__ import annotations

from contextlib import nullcontext

import pytest
from hypothesis import HealthCheck
from hypothesis import given
from hypothesis import settings
from hypothesis import strategies as st
from pytest_httpserver import HTTPServer

from harborapi.client import HarborAsyncClient
from harborapi.exceptions import StatusError
from harborapi.models import OIDCTestReq


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 400, 401, 403, 404, 500])
@given(st.builds(OIDCTestReq))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_test_oidc_mock(
    async_client: HarborAsyncClient,
    httpserver: HTTPServer,
    status: int,
    oidcreq: OIDCTestReq,
):
    httpserver.expect_oneshot_request(
        "/api/v2.0/system/oidc/ping",
        method="POST",
        json=oidcreq.model_dump(mode="json", exclude_unset=True),
    ).respond_with_data(status=status)

    if status == 200:
        ctx = nullcontext()
    else:
        ctx = pytest.raises(StatusError)
    with ctx as exc_info:
        await async_client.test_oidc(oidcreq=oidcreq)
    if status == 200:
        assert exc_info is None
    else:
        assert exc_info is not None
        assert exc_info.value.status_code == status
        assert exc_info.value.__cause__.response.status_code == status
