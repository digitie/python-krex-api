"""공유 예산·취소·동시 진단·HTTP 세션과 오류 표시 계약."""

import asyncio
import inspect
import logging
import traceback
from typing import Any
from urllib.parse import quote

import httpx
import pytest

import krex
from krex import AsyncTokenBucket, KrexClient
from krex._http import KrexHttp
from krex.exceptions import KrexAuthError, KrexParseError, KrexQuotaExceededError


def payload(value: str = "0010") -> dict[str, Any]:
    return {"code": "SUCCESS", "count": 1, "list": [{"marker": value}]}


class CountingBucket(AsyncTokenBucket):
    def __init__(self) -> None:
        super().__init__(10000)
        self.count = 0

    async def acquire(self) -> None:
        await super().acquire()
        self.count += 1


def test_public_api_is_async_and_local_reference_remains_pure() -> None:
    assert not hasattr(krex, "AsyncKrexClient")
    assert not hasattr(KrexClient, "aio")
    assert not hasattr(KrexClient, "adebug_call")
    assert not hasattr(KrexHttp, "close")
    client = KrexClient(ex_api_key="fake-key")
    assert client.rate_limiter.capacity == 1
    assert inspect.iscoroutinefunction(client.traffic.by_ic)
    assert inspect.iscoroutinefunction(client.restarea.latest_weather)
    assert inspect.iscoroutinefunction(client.debug_call)
    assert not inspect.iscoroutinefunction(client.reference.routes)
    assert client.reference.routes()


async def test_shared_budget_covers_two_providers_retries_redirects_and_debug() -> None:
    bucket = CountingBucket()
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        if len(calls) == 2:
            raise httpx.ConnectError("offline")
        if len(calls) == 3:
            return httpx.Response(302, headers={"Location": "/final"})
        if "serviceKey" in request.url.params:
            return httpx.Response(
                200,
                json={
                    "response": {
                        "header": {"resultCode": "00"},
                        "body": {"items": {"item": [{"code": "0010"}]}, "totalCount": "1"},
                    }
                },
            )
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as session:
        async with KrexClient(
            ex_api_key="test-key", session=session, rate_limiter=bucket, retry_backoff=0
        ) as client:
            await client.traffic.by_route(time_unit="1", route_no="0010")
            run = await client.debug_call("traffic.by_route", time_unit="1", route_no="0010")
            assert run.error is None
            assert run.parsed.items[0]["marker"] == "0010"
        http = KrexHttp(go_api_key="go-key", session=session, rate_limiter=bucket)
        result = await http.get_go("https://api.example.test/items")
        assert result.items[0]["code"] == "0010"
        await http.aclose()
        assert not session.is_closed
    assert bucket.count == len(calls) == 6


@pytest.mark.parametrize(
    "status,error", [(401, KrexAuthError), (403, KrexAuthError), (429, KrexQuotaExceededError)]
)
async def test_auth_and_quota_fail_without_retry(status: int, error: type[Exception]) -> None:
    bucket = CountingBucket()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status))
    ) as session:
        http = KrexHttp(ex_api_key="test-key", session=session, rate_limiter=bucket, max_retries=5)
        with pytest.raises(error):
            await http.get_ex("/test")
    assert bucket.count == 1


async def test_pool_ownership_closed_guard_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        KrexClient(ex_api_key="fake-key", max_rps=float("nan"))
    with httpx.Client() as sync_session:
        with pytest.raises(TypeError, match="async"):
            KrexClient(ex_api_key="fake-key", session=sync_session)

    factory = httpx.AsyncClient
    created: list[httpx.AsyncClient] = []

    class OwnedClient(factory):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload())),
                **kwargs,
            )
            created.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", OwnedClient)
    client = KrexClient(ex_api_key="fake-key")
    assert not created
    async with client:
        await client.traffic.by_route(time_unit="1", route_no="0010")
    await client.aclose()
    assert len(created) == 1 and created[0].is_closed
    with pytest.raises(RuntimeError, match="closed"):
        await client.traffic.by_route(time_unit="1", route_no="0010")


async def test_concurrent_diagnostics_are_isolated_and_cancellation_restores() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("routeNo") == "0010":
            entered.set()
            await release.wait()
            return httpx.Response(200, json=payload("0010"))
        return httpx.Response(403, text="denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        async with KrexClient(ex_api_key="test-key", session=session, max_rps=10000) as client:
            slow = asyncio.create_task(
                client.debug_call("traffic.by_route", time_unit="1", route_no="0010")
            )
            await asyncio.wait_for(entered.wait(), timeout=2)
            failed = await client.debug_call("traffic.by_route", time_unit="1", route_no="0020")
            assert failed.response["status_code"] == 403
            assert failed.request["query"]["routeNo"] == "0020"
            assert failed.error and failed.error["type"] == "KrexAuthError"
            slow.cancel()
            with pytest.raises(asyncio.CancelledError):
                await slow
            assert client._http._diagnostics.get() is None
            release.set()
            successful = await client.debug_call("traffic.by_route", time_unit="1", route_no="0010")
            assert successful.error is None
            assert successful.request["query"]["routeNo"] == "0010"
            assert successful.response["status_code"] == 200


async def test_model_error_and_debug_payload_do_not_expose_keys() -> None:
    key = "synthetic/key+value"
    original = payload()
    original["list"][0].update(echo=key, encoded=quote(key, safe=""))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=original))
    ) as session:
        async with KrexClient(ex_api_key=key, session=session) as client:
            run = await client.debug_call("traffic.by_route", time_unit="1", route_no="0010")
            assert run.error is None
            assert isinstance(run.parsed.items, tuple)
            assert key not in str(krex.jsonable(run))
            assert quote(key, safe="") not in str(krex.jsonable(run))
            assert original["list"][0]["echo"] == key

    malformed = {"code": "SUCCESS", "list": [{"conzoneId": "0010", "speed": key}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=malformed))
    ) as session:
        async with KrexClient(ex_api_key=key, session=session) as client:
            with pytest.raises(KrexParseError) as caught:
                await client.traffic.flow(route_no="0010")
            assert key not in str(caught.value)
            assert key not in str(caught.value.response)
            assert key not in "".join(traceback.format_exception(caught.value))


async def test_automatic_auth_flow_is_rejected_before_transmission() -> None:
    bucket = CountingBucket()
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        http = KrexHttp(ex_api_key="key", session=session, rate_limiter=bucket)
        # 세션 생성 이후 바꾼 인증 설정도 최초 송신 전에 검증한다.
        session.auth = httpx.DigestAuth("user", "password")
        with pytest.raises(TypeError, match="authentication"):
            await http.get_ex("/test")
        assert not sent and bucket.count == 0
        session.auth = httpx.BasicAuth("user", "password")
        await http.get_ex("/test")
        assert len(sent) == bucket.count == 1


async def test_provider_code_and_httpx_logs_mask_keys(caplog: pytest.LogCaptureFixture) -> None:
    key = "synthetic/key+value"
    caplog.set_level(logging.INFO, logger="httpx")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": key, "message": "denied"})
        )
    ) as session:
        async with KrexClient(ex_api_key=key, session=session) as client:
            with pytest.raises(krex.KrexError) as caught:
                await client.traffic.by_route(route_no="0010", time_unit="1")
            assert key not in str(vars(caught.value))
            assert key not in caplog.text
            assert quote(key, safe="") not in caplog.text


async def test_auth_changed_while_waiting_is_rejected_before_send() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    sent: list[httpx.Request] = []

    class GateBucket(CountingBucket):
        async def acquire(self) -> None:
            entered.set()
            await release.wait()
            await super().acquire()

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
        http = KrexHttp(ex_api_key="key", session=session, rate_limiter=GateBucket())
        task = asyncio.create_task(http.get_ex("/test"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        session.auth = httpx.DigestAuth("user", "password")
        release.set()
        with pytest.raises(TypeError, match="authentication"):
            await task
    assert not sent
