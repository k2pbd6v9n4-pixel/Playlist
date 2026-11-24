"""Small HTTP helper with retries for rate limits and server errors."""
from __future__ import annotations

import time
from typing import Any, Callable

import requests


class ApiError(Exception):
    """An API call failed. `status` is the HTTP status code (0 for network errors)."""

    def __init__(self, service: str, status: int, message: str, path: str = ""):
        self.service = service
        self.status = status
        self.message = message
        self.path = path
        super().__init__(f"{service} API error {status} on {path}: {message}")


def _error_text(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):  # Spotify: {"error": {"status": 400, "message": "..."}}
            return str(err.get("message") or err)[:300]
        if isinstance(err, str):  # Spotify accounts: {"error": "invalid_grant", "error_description": "..."}
            return f"{err}: {body.get('error_description', '')}"[:300]
        errors = body.get("errors")  # Apple: {"errors": [{"title": ..., "detail": ...}]}
        if isinstance(errors, list) and errors:
            e = errors[0]
            return f"{e.get('title', '')}: {e.get('detail', '')}"[:300]
    return str(body)[:300]


def call(
    session: requests.Session,
    service: str,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: Any = None,
    data: dict | None = None,
    headers: dict | None = None,
    max_tries: int = 5,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Make a request and return the JSON body ({} when empty). Raises ApiError."""
    path = url.split("?", 1)[0].replace("https://", "")
    for attempt in range(max_tries):
        try:
            resp = session.request(
                method, url, params=params, json=json, data=data, headers=headers, timeout=30
            )
        except requests.RequestException as exc:
            if attempt < max_tries - 1:
                sleep(2 ** attempt)
                continue
            raise ApiError(service, 0, f"network error: {exc.__class__.__name__}", path) from exc

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "5")
            try:
                wait = float(retry_after)
            except ValueError:
                wait = 5.0
            if wait > 120 or attempt == max_tries - 1:
                raise ApiError(service, 429, f"rate limited (retry after {retry_after}s)", path)
            sleep(wait + 1)
            continue
        if resp.status_code >= 500 and attempt < max_tries - 1:
            sleep(2 ** attempt)
            continue
        if not resp.ok:
            raise ApiError(service, resp.status_code, _error_text(resp), path)
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {}
    raise ApiError(service, 0, "gave up after retries", path)
