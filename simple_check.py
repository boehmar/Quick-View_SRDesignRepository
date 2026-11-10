"""
Simple status check: runs each network test, then each external service
monitor, and prints one line per test with its result and response time.

Needs network_check.py in the same folder and the monitors in ./external_monitoring.

Run:  python simple_check.py
      python simple_check.py --json
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "external_monitoring"))

import network_check
from slack_status import get_slack_status
from github_status import get_github_status
from dropbox_status import get_dropbox_status


def run_checks() -> list:
    """Return one dict per test: {category, name, ok, status, response_ms, error}."""
    results = []

    # --- Network tests (the functions from network_check.py) ---
    for host, port in network_check.IP_TARGETS:
        r = network_check.test_tcp(host, port)
        results.append({
            "category": "Internet by IP", "name": r["target"], "ok": r["ok"],
            "status": "Reachable" if r["ok"] else "Unreachable",
            "response_ms": r.get("ms"),
            "error": None if r["ok"] else network_check.friendly_error(r["error"]),
        })

    for name in network_check.DNS_NAMES:
        r = network_check.test_dns(name)
        results.append({
            "category": "DNS", "name": name, "ok": r["ok"],
            "status": "Resolved" if r["ok"] else "Failed",
            "response_ms": r.get("ms"),
            "error": None if r["ok"] else network_check.friendly_error(r["error"]),
        })

    r = network_check.test_http()
    page_ok = r["ok"] and r.get("expected_content", False)
    results.append({
        "category": "Web (HTTP)", "name": network_check.HTTP_URL, "ok": page_ok,
        "status": "Loaded" if page_ok else ("Unexpected page" if r["ok"] else "Failed"),
        "response_ms": r.get("ms"),
        "error": None if r["ok"] else network_check.friendly_error(r["error"]),
    })

    # --- External services (response time = how long the status API call took) ---
    for label, func in [("Slack", get_slack_status),
                        ("GitHub", get_github_status),
                        ("Dropbox", get_dropbox_status)]:
        start = time.perf_counter()
        try:
            data = func().to_dict()
            ms = int((time.perf_counter() - start) * 1000)
            results.append({
                "category": "External API", "name": label,
                "ok": data.get("status") == "Operational",
                "status": data.get("status"),
                "response_ms": ms,
                "error": data.get("error"),
            })
        except Exception as e:  # a broken monitor shouldn't stop the rest
            results.append({
                "category": "External API", "name": label, "ok": False,
                "status": "Unknown", "response_ms": int((time.perf_counter() - start) * 1000),
                "error": f"{type(e).__name__}: {e}",
            })

    return results


def print_report(results: list) -> None:
    current = None
    for r in results:
        if r["category"] != current:
            current = r["category"]
            print(f"\n{current}")
        mark = "PASS" if r["ok"] else "FAIL"
        ms = f"{r['response_ms']} ms" if r["response_ms"] is not None else "-"
        line = f"  [{mark}]  {r['name']:<42} {r['status']:<14} {ms:>8}"
        if r["error"]:
            line += f"   ({r['error']})"
        print(line)

    failed = sum(1 for r in results if not r["ok"])
    print(f"\n{'All tests passed.' if not failed else f'{failed} of {len(results)} tests did not pass.'}")


if __name__ == "__main__":
    results = run_checks()
    if "--json" in sys.argv:
        print(json.dumps(results, indent=2))
    else:
        print_report(results)
    sys.exit(0 if all(r["ok"] for r in results) else 1)
