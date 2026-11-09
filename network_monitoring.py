"""
Basic network tests that run locally on the user's device.

Tests:
  1. Internet access by IP    - TCP connect to well-known public IPs (no DNS needed)
  2. DNS resolution           - resolve several hostnames with the device's own resolver
  3. Web access (HTTP)        - fetch a tiny known page; also detects captive portals

Comparing 1 and 2 tells you WHERE the problem is:
  IP works, DNS fails  -> DNS problem
  Nothing works        -> no connectivity (Wi-Fi/cable, VPN, firewall)

Changes in this version:
  - All tests run in parallel (worst case ~2x TIMEOUT instead of ~7x).
  - A failed test is retried once before it is reported as failed.
  - Failures carry a machine-readable "kind" (timeout, dns, refused, ...) plus
    error_type / errno, so nothing has to parse error text.
  - HTTP 4xx/5xx responses count as "server reached" and feed portal detection.
  - Proxy case: web works but local DNS/raw IP fails -> reported as OK with a note.
  - Result includes a UTC timestamp and total duration.
  - Hostname / local IP are only included if you ask for them (privacy).

Uses only the Python standard library: no pip install needed.
Run:  python network_monitoring.py          (plain-language report)
      python network_monitoring.py --json   (raw data for other programs)
"""

from __future__ import annotations

import json
import platform
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TIMEOUT = 5          # seconds per attempt
RETRIES = 1          # extra attempts after a failure
RETRY_DELAY = 0.3    # seconds to wait before retrying

# Cloudflare, Google, Quad9 (port 443 is the most likely to be allowed outbound)
IP_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)]

DNS_NAMES = ["www.microsoft.com", "www.google.com", "github.com"]

# Microsoft's own connectivity-check page (the one Windows uses)
HTTP_URL = "http://www.msftconnecttest.com/connecttest.txt"
HTTP_EXPECTED = "Microsoft Connect Test"

# errno values by meaning (Windows WSA codes + Linux/macOS equivalents)
_ERRNO_TIMEOUT = {10060, 110, 60}
_ERRNO_REFUSED = {10061, 111, 61}
_ERRNO_UNREACHABLE = {10051, 10065, 101, 113, 51, 65}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _classify(exc: BaseException) -> str:
    """Map an exception to a simple category without reading its message text."""
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        exc = exc.reason  # unwrap: URLError hides the real cause in .reason
    code = getattr(exc, "errno", None)
    if isinstance(exc, (TimeoutError, socket.timeout)) or code in _ERRNO_TIMEOUT:
        return "timeout"
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, ConnectionRefusedError) or code in _ERRNO_REFUSED:
        return "refused"
    if code in _ERRNO_UNREACHABLE:
        return "unreachable"
    if isinstance(exc, ssl.SSLError):
        return "ssl"
    return "other"


def _failure(base: dict, exc: BaseException) -> dict:
    root = exc.reason if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException) else exc
    return {
        **base,
        "ok": False,
        "kind": _classify(exc),
        "error_type": type(root).__name__,
        "errno": getattr(root, "errno", None),
        "error": str(root),  # for logs only; never branch on this
    }


def _with_retry(fn, *args) -> dict:
    """Run a test; if it fails, wait briefly and try again before giving up."""
    result = fn(*args)
    attempts = 1
    while not result["ok"] and attempts <= RETRIES:
        time.sleep(RETRY_DELAY)
        result = fn(*args)
        attempts += 1
    result["attempts"] = attempts
    return result


def _call_with_timeout(fn, timeout: float, *args):
    """
    Run fn(*args) in a daemon thread and stop waiting after `timeout` seconds.
    (getaddrinfo has no timeout option. A daemon thread means a hung lookup can't
    keep the program from exiting.)
    """
    box: dict = {}

    def runner():
        try:
            box["value"] = fn(*args)
        except BaseException as e:  # noqa: BLE001 - we re-raise it below
            box["error"] = e

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"no answer after {timeout}s")
    if "error" in box:
        raise box["error"]
    return box["value"]


# --------------------------------------------------------------------------
# Individual tests (each returns a dict with at least "ok")
# --------------------------------------------------------------------------

def test_tcp(host: str, port: int) -> dict:
    base = {"target": f"{host}:{port}"}
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            pass
        return {**base, "ok": True, "ms": _ms(start)}
    except OSError as e:
        return _failure(base, e)


def test_dns(name: str) -> dict:
    base = {"name": name}
    start = time.perf_counter()
    try:
        results = _call_with_timeout(socket.getaddrinfo, TIMEOUT, name, 443, 0, socket.SOCK_STREAM)
        addresses = sorted({r[4][0] for r in results})
        return {**base, "ok": True, "ms": _ms(start), "addresses": addresses[:3]}
    except OSError as e:  # gaierror and TimeoutError are both OSError subclasses
        return _failure(base, e)


def test_http() -> dict:
    """Uses the system proxy settings automatically, like a browser would."""
    base = {"url": HTTP_URL}
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(HTTP_URL, timeout=TIMEOUT) as resp:
            body = resp.read(200).decode("utf-8", errors="replace").strip()
            return {**base, "ok": True, "ms": _ms(start), "status": resp.status,
                    "expected_content": HTTP_EXPECTED in body}
    except urllib.error.HTTPError as e:
        # A 403/302/etc. means a server answered. Often a captive portal or proxy page.
        return {**base, "ok": True, "ms": _ms(start), "status": e.code,
                "expected_content": False}
    except Exception as e:  # URLError, timeout, proxy errors, etc.
        return _failure(base, e)


def local_ip() -> str | None:
    """Find the IP of the active network adapter. UDP connect sends no packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


# --------------------------------------------------------------------------
# Diagnosis
# --------------------------------------------------------------------------

def check_network(include_device: bool = False) -> dict:
    started = time.perf_counter()

    # Run every test at the same time
    with ThreadPoolExecutor(max_workers=len(IP_TARGETS) + len(DNS_NAMES) + 1) as pool:
        ip_futures = [pool.submit(_with_retry, test_tcp, h, p) for h, p in IP_TARGETS]
        dns_futures = [pool.submit(_with_retry, test_dns, n) for n in DNS_NAMES]
        http_future = pool.submit(_with_retry, test_http)

        ip_results = [f.result() for f in ip_futures]
        dns_results = [f.result() for f in dns_futures]
        http_result = http_future.result()

    ip_ok = any(r["ok"] for r in ip_results)
    dns_ok = any(r["ok"] for r in dns_results)
    http_ok = http_result["ok"]
    http_expected = http_ok and http_result.get("expected_content", False)
    portal = http_ok and not http_expected
    internet_ok = ip_ok or http_ok  # HTTP can work through a proxy when raw IPs are blocked

    # Work out the most likely diagnosis
    if not internet_ok and not dns_ok:
        state, summary = "down", "No connectivity: check Wi-Fi/cable, VPN, or firewall."
    elif not dns_ok and http_expected:
        # The browser-style request worked even though local lookups failed:
        # most likely a proxy is doing the lookups for us.
        state, summary = "ok", "Web access works (likely through a proxy), though direct DNS lookups failed."
    elif internet_ok and not dns_ok:
        state, summary = "degraded", "Internet reachable but DNS resolution is failing."
    elif dns_ok and not internet_ok:
        state, summary = "degraded", "DNS works but internet traffic is blocked."
    elif portal:
        state, summary = "degraded", "Web request was altered: possible captive portal or proxy login."
    elif not all(r["ok"] for r in dns_results):
        state, summary = "degraded", "Some website names could not be looked up. Browsing may be unreliable."
    elif not http_ok:
        state, summary = "degraded", "Internet and DNS work, but a test web page would not load. Browsing may be affected."
    else:
        state, summary = "ok", "Internet access and DNS resolution are working."

    details = {
        "summary": summary,
        "os": platform.system(),
        "internet_by_ip": ip_results,
        "dns": dns_results,
        "http": http_result,
    }
    if include_device:  # off by default: not needed for diagnosis
        details["device"] = {"hostname": socket.gethostname(), "local_ip": local_ip()}

    return {
        "name": "Network",
        "state": state,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_ms": _ms(started),
        "details": details,
    }


# --------------------------------------------------------------------------
# Plain-language report
# --------------------------------------------------------------------------

IP_LABELS = {"1.1.1.1": "Cloudflare", "8.8.8.8": "Google", "9.9.9.9": "Quad9"}

HEADLINES = {
    "ok": "[ OK ]  Everything is working",
    "degraded": "[ !! ]  Something is not working properly",
    "down": "[FAIL]  No internet connection",
    "unknown": "[ ?? ]  Could not determine status",
}

FRIENDLY_KINDS = {
    "timeout": "no response (timed out)",
    "dns": "could not find this website name",
    "unreachable": "no route to the internet",
    "refused": "connection was refused",
    "ssl": "secure connection failed",
}


def friendly_error(kind: str | None) -> str:
    """Turn an error category into something a non-technical reader can follow."""
    return FRIENDLY_KINDS.get(kind or "", "failed")


def format_report(result: dict) -> str:
    d = result["details"]
    lines = []
    bar = "=" * 58

    lines += [bar, "  NETWORK CHECK", bar, ""]
    lines += [f"  RESULT:  {HEADLINES.get(result['state'], result['state'])}",
              f"           {d['summary']}",
              f"           (checked {result['checked_at']} in {result['duration_ms']} ms)", ""]

    if "device" in d:
        dev = d["device"]
        lines += ["  YOUR DEVICE",
                  f"    Computer name:    {dev['hostname']}",
                  f"    Network address:  {dev['local_ip'] or 'not found'}",
                  f"    Operating system: {d['os']}", ""]

    lines += ["  TEST 1: Can your device reach the internet?",
              "          (connects straight to well-known servers)"]
    for r in d["internet_by_ip"]:
        host = r["target"].split(":")[0]
        label = f"{IP_LABELS.get(host, host)} ({host})"
        if r["ok"]:
            lines.append(f"    [PASS]  {label:<22} connected in {r['ms']} ms")
        else:
            lines.append(f"    [FAIL]  {label:<22} {friendly_error(r.get('kind'))}")
    lines.append("")

    lines += ["  TEST 2: Can your device look up website names? (DNS)",
              "          (turns a name like google.com into an address)"]
    for r in d["dns"]:
        if r["ok"]:
            lines.append(f"    [PASS]  {r['name']:<22} found in {r['ms']} ms")
        else:
            lines.append(f"    [FAIL]  {r['name']:<22} {friendly_error(r.get('kind'))}")
    lines.append("")

    h = d["http"]
    lines += ["  TEST 3: Can your device load a web page?"]
    if h["ok"] and h.get("expected_content"):
        lines.append(f"    [PASS]  Test page loaded in {h['ms']} ms")
    elif h["ok"]:
        lines.append("    [FAIL]  A page loaded, but it was not the expected one.")
        lines.append("            You may need to sign in to a Wi-Fi or proxy login page.")
    else:
        lines.append(f"    [FAIL]  Page did not load ({friendly_error(h.get('kind'))})")
    lines += ["", bar]
    return "\n".join(lines)


if __name__ == "__main__":
    result = check_network(include_device="--device" in sys.argv)
    if "--json" in sys.argv:  # raw output for other programs
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))
    sys.exit(0 if result["state"] == "ok" else 1)