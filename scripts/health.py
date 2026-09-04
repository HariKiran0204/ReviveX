"""Call RecoverAI /health and /ready. Used by `make health`."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("NEXT_PUBLIC_API_URL", "http://localhost:8000")


def _get(path: str) -> tuple[int, object]:
    request = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed: object = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def main() -> int:
    health_status, health_body = _get("/health")
    ready_status, ready_body = _get("/ready")
    print(json.dumps({"health": {"status": health_status, "body": health_body}}, indent=2))
    print(json.dumps({"ready": {"status": ready_status, "body": ready_body}}, indent=2))
    if health_status != 200 or ready_status != 200:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
