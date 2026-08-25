import asyncio
import json
from pathlib import Path

import httpx

from outgy import saapa

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def respond(name_or_status: str | int) -> httpx.Response:
    if isinstance(name_or_status, int):
        return httpx.Response(name_or_status)
    return httpx.Response(200, json=load(name_or_status))


def make_client(routes: dict[str, str | int | callable]) -> saapa.SaapaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(request.url.path)
        if route is None:
            raise AssertionError(f"unexpected path {request.url.path}")
        if callable(route):
            return route(request)
        return respond(route)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return saapa.SaapaClient(http, "https://api.test")


def run(coroutine):
    return asyncio.run(coroutine)
