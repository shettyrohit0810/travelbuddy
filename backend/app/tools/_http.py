import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("app.tools.http")

DEFAULT_TIMEOUT = 8


def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: Optional[int] = None) -> Any:
    """Stdlib-only JSON GET. No new HTTP dependency (see KICKOFF_PROMPT.md ask-before-adding-deps rule)."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_form(url: str, data: dict, headers: Optional[dict] = None,
              timeout: Optional[int] = None) -> Any:
    """Stdlib-only JSON-returning POST with form-encoded body (OAuth2 client-credentials,
    and Overpass, which wants the query in a `data` field and is slow by design)."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req_headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout or DEFAULT_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))
