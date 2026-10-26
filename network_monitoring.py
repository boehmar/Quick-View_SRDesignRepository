"""
Basic network tests that run locally on the user's device.

Tests:
  1. Internet access by IP    - TCP connect to well-known public IPs (no DNS needed)
  2. DNS resolution           - resolve several hostnames with the device's own resolver
  3. Web access (HTTP)        - fetch a tiny known page; also detects captive portals

Comparing 1 and 2 tells you WHERE the problem is:
  IP works, DNS fails  -> DNS problem
  Nothing works        -> no connectivity (Wi-Fi/cable, VPN, firewall)

Uses only the Python standard library: no pip install needed.
Run:  python network_check.py          (plain-language report)
      python network_check.py --json   (raw data for other programs)
"""

import json
import platform
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

TIMEOUT = 5  # seconds per test

# Cloudflare, Google, Quad9 (port 443 is the most likely to be allowed outbound)
IP_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("9.9.9.9", 443)]

DNS_NAMES = ["www.microsoft.com", "www.google.com", "github.com"]

# Microsoft's own connectivity-check page (the one Windows uses)
HTTP_URL = "http://www.msftconnecttest.com/connecttest.txt"
HTTP_EXPECTED = "Microsoft Connect Test"


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def test_tcp(host: str, port: int) -> dict:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            pass
        return {"target": f"{host}:{port}", "ok": True, "ms": _ms(start)}
    except OSError as e:
        return {"target": f"{host}:{port}", "ok": False, "error": str(e)}


def test_dns(name: str) -> dict:
    """getaddrinfo has no timeout option, so run it in a thread and stop waiting."""
    start = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(socket.getaddrinfo, name, 443, 0, socket.SOCK_STREAM)
    try:
        results = future.result(timeout=TIMEOUT)
        addresses = sorted({r[4][0] for r in results})
        return {"name": name, "ok": True, "ms": _ms(start), "addresses": addresses[:3]}
    except FutureTimeout:
        return {"name": name, "ok": False, "error": f"timed out after {TIMEOUT}s"}
    except OSError as e:
        return {"name": name, "ok": False, "error": str(e)}
    finally:
        pool.shutdown(wait=False)


def test_http() -> dict:
    """Uses the system proxy settings automatically, like a browser would."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(HTTP_URL, timeout=TIMEOUT) as resp:
            body = resp.read(200).decode("utf-8", errors="replace").strip()
            return {
                "url": HTTP_URL,
                "ok": True,
                "ms": _ms(start),
                "status": resp.status,
                "expected_content": HTTP_EXPECTED in body,
            }
    except Exception as e:  # URLError, timeout, proxy errors, etc.
        return {"url": HTTP_URL, "ok": False, "error": str(e)}


def local_ip() -> str | None:
    """Find the IP of the active network adapter. UDP connect sends no packets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def check_network() -> dict:
    ip_results = [test_tcp(h, p) for h, p in IP_TARGETS]
    dns_results = [test_dns(n) for n in DNS_NAMES]
    http_result = test_http()

    ip_ok = any(r["ok"] for r in ip_results)
    dns_ok = any(r["ok"] for r in dns_results)
    http_ok = http_result["ok"]
    portal = http_ok and not http_result.get("expected_content")
    internet_ok = ip_ok or http_ok  # HTTP can work through a proxy when raw IPs are blocked

    # Work out the most likely diagnosis
    if not internet_ok and not dns_ok:
        state, summary = "down", "No connectivity: check Wi-Fi/cable, VPN, or firewall."
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

    return {
        "name": "Network",
        "state": state,
        "details": {
            "summary": summary,
            "device": {
                "hostname": socket.gethostname(),
                "local_ip": local_ip(),
                "os": platform.system(),
            },
            "internet_by_ip": ip_results,
            "dns": dns_results,
            "http": http_result,
        },
    }


IP_LABELS = {"1.1.1.1": "Cloudflare", "8.8.8.8": "Google", "9.9.9.9": "Quad9"}

HEADLINES = {
    "ok": "[ OK ]  Everything is working",
    "degraded": "[ !! ]  Something is not working properly",
    "down": "[FAIL]  No internet connection",
    "unknown": "[ ?? ]  Could not determine status",
}


def friendly_error(error: str) -> str:
    """Turn technical error text into something a non-technical reader can follow."""
    e = error.lower()
    if "timed out" in e:
        return "no response (timed out)"
    if "getaddrinfo" in e or "name or service not known" in e or "11001" in e:
        return "could not find this website name"
    if "unreachable" in e or "10051" in e or "10065" in e:
        return "no route to the internet"
    if "refused" in e or "10061" in e:
        return "connection was refused"
    return "failed"


def format_report(result: dict) -> str:
    d = result["details"]
    lines = []
    bar = "=" * 58

    lines += [bar, "  NETWORK CHECK", bar, ""]
    lines += [f"  RESULT:  {HEADLINES.get(result['state'], result['state'])}",
              f"           {d['summary']}", ""]

    dev = d["device"]
    lines += ["  YOUR DEVICE",
              f"    Computer name:    {dev['hostname']}",
              f"    Network address:  {dev['local_ip'] or 'not found'}",
              f"    Operating system: {dev['os']}", ""]

    lines += ["  TEST 1: Can your device reach the internet?",
              "          (connects straight to well-known servers)"]
    for r in d["internet_by_ip"]:
        host = r["target"].split(":")[0]
        label = f"{IP_LABELS.get(host, host)} ({host})"
        if r["ok"]:
            lines.append(f"    [PASS]  {label:<22} connected in {r['ms']} ms")
        else:
            lines.append(f"    [FAIL]  {label:<22} {friendly_error(r['error'])}")
    lines.append("")

    lines += ["  TEST 2: Can your device look up website names? (DNS)",
              "          (turns a name like google.com into an address)"]
    for r in d["dns"]:
        if r["ok"]:
            lines.append(f"    [PASS]  {r['name']:<22} found in {r['ms']} ms")
        else:
            lines.append(f"    [FAIL]  {r['name']:<22} {friendly_error(r['error'])}")
    lines.append("")

    h = d["http"]
    lines += ["  TEST 3: Can your device load a web page?",]
    if h["ok"] and h.get("expected_content"):
        lines.append(f"    [PASS]  Test page loaded in {h['ms']} ms")
    elif h["ok"]:
        lines.append("    [FAIL]  A page loaded, but it was not the expected one.")
        lines.append("            You may need to sign in to a Wi-Fi or proxy login page.")
    else:
        lines.append(f"    [FAIL]  Page did not load ({friendly_error(h['error'])})")
    lines += ["", bar]
    return "\n".join(lines)


if __name__ == "__main__":
    result = check_network()
    if "--json" in sys.argv:  # raw output for other programs
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))
    sys.exit(0 if result["state"] == "ok" else 1)