#!/usr/bin/env python3
"""Poll an HTTP URL until it returns 2xx or the timeout expires."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT_SECONDS = 180
DEFAULT_INTERVAL_SECONDS = 2


def wait_for_url(url: str, *, timeout: float, interval: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if 200 <= response.status < 300:
                    return
                last_error = RuntimeError(f"unexpected status {response.status}")
        except urllib.error.HTTPError as exc:
            if 200 <= exc.code < 300:
                return
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - surface the last transport error
            last_error = exc
        time.sleep(interval)

    message = f"timed out waiting for {url}"
    if last_error is not None:
        message = f"{message} (last error: {last_error})"
    raise SystemExit(message)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: wait_for_http.py <url> [timeout_seconds]")

    url = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_TIMEOUT_SECONDS
    wait_for_url(url, timeout=timeout, interval=DEFAULT_INTERVAL_SECONDS)
    print(f"ready: {url}")


if __name__ == "__main__":
    main()
