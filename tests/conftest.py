"""Shared fixtures: an aiohttp mock that records each request it answers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import ClientResponse
from aioresponses import aioresponses

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from yarl import URL


class _MockResponse(ClientResponse):
    """A ``ClientResponse`` that aioresponses can build on aiohttp 3.14+.

    aiohttp 3.14 made ``stream_writer`` a required argument, which aioresponses 0.7.9
    does not pass. The mock never writes a request, so a stand-in with no output will do.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
        super().__init__(*args, **kwargs)


@dataclass(frozen=True)
class RecordedRequest:
    """One request the mock answered, as calm-client sent it."""

    method: str
    url: URL
    headers: Mapping[str, str]
    json: Any


@dataclass
class Route:
    """A mocked endpoint and the requests that reached it."""

    calls: list[RecordedRequest] = field(default_factory=list)

    @property
    def called(self) -> bool:
        """True once any request reached this route."""
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        """How many requests reached this route."""
        return len(self.calls)

    @property
    def last(self) -> RecordedRequest:
        """The most recent request on this route."""
        return self.calls[-1]


class HttpMock:
    """Register canned aiohttp responses by method and URL; any query string matches.

    Each ``get``/``post``/``delete`` takes the response as keywords: ``status``,
    ``payload`` (a JSON body), ``body`` (raw text or bytes), ``headers`` or ``exception``
    (raised instead of answering). Routes answer every matching request.
    """

    def __init__(self, mocker: aioresponses) -> None:
        """Wrap an active aioresponses mocker."""
        self._mocker = mocker
        self.calls: list[RecordedRequest] = []

    def _add(self, method: str, url: str, **response: Any) -> Route:
        route = Route()

        def record(request_url: URL, **kwargs: Any) -> None:
            call = RecordedRequest(method, request_url, dict(kwargs.get("headers") or {}), kwargs.get("json"))
            route.calls.append(call)
            self.calls.append(call)

        pattern = re.compile(re.escape(url) + r"(\?.*)?$")
        self._mocker.add(pattern, method, callback=record, repeat=True, response_class=_MockResponse, **response)
        return route

    def get(self, url: str, **response: Any) -> Route:
        """Mock a GET endpoint."""
        return self._add("GET", url, **response)

    def post(self, url: str, **response: Any) -> Route:
        """Mock a POST endpoint."""
        return self._add("POST", url, **response)

    def delete(self, url: str, **response: Any) -> Route:
        """Mock a DELETE endpoint."""
        return self._add("DELETE", url, **response)


@pytest.fixture
def http_mock() -> Iterator[HttpMock]:
    """Intercept every aiohttp request; unmocked URLs fail with a connection error."""
    with aioresponses() as mocker:
        yield HttpMock(mocker)
