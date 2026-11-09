"""

It runs the network checks, breaks the result into individual services
(Internet by IP, DNS, Web/HTTP), also queries the external service
monitors in ./external_monitoring (Slack, GitHub, Dropbox), judges each
one, and gives a single verdict on whether every service is functional.

Other check groups can be added with engine.register(...) - see the
bottom of this file. Each group is isolated: if one crashes or hangs,
it is reported as "unknown" and the others still run.

Exit code: 0 = all services OK, 1 = degraded, 2 = down, 3 = unknown.
"""

import importlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, asdict
from typing import Callable

import network_monitoring  # the script you provided

# Severity order: higher is worse. "unknown" sits between degraded and down
# so that a check we couldn't run is never mistaken for a healthy one.
SEVERITY = {"ok": 0, "degraded": 1, "down": 2, "unknown": 3}
EXIT_CODES = {"ok": 0, "degraded": 1, "down": 2, "unknown": 3}
LABELS = {"ok": "[ OK ]", "degraded": "[ !! ]", "down": "[FAIL]", "unknown": "[ ?? ]"}


@dataclass
class ServiceResult:
    service: str
    state: str                       # ok | degraded | down | unknown
    summary: str
    details: dict = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class Report:
    overall_state: str
    all_functional: bool
    summary: str
    services: list
    diagnosis: str = ""              # check_network's own root-cause summary
    total_ms: int = 0


# --------------------------------------------------------------------------
# Adapters: turn network_check's raw output into per-service verdicts
# --------------------------------------------------------------------------

def _ratio_state(results: list) -> str:
    passed = sum(1 for r in results if r["ok"])
    if passed == len(results):
        return "ok"
    return "down" if passed == 0 else "degraded"


def judge_internet(details: dict) -> ServiceResult:
    results = details["internet_by_ip"]
    passed = sum(1 for r in results if r["ok"])
    state = _ratio_state(results)
    return ServiceResult(
        "Internet (by IP)", state,
        f"{passed}/{len(results)} public servers reachable",
        {"tests": results},
    )


def judge_dns(details: dict) -> ServiceResult:
    results = details["dns"]
    passed = sum(1 for r in results if r["ok"])
    state = _ratio_state(results)
    return ServiceResult(
        "DNS resolution", state,
        f"{passed}/{len(results)} hostnames resolved",
        {"tests": results},
    )


def judge_http(details: dict) -> ServiceResult:
    h = details["http"]
    if not h["ok"]:
        return ServiceResult("Web access (HTTP)", "down",
                             f"Test page did not load: {network_monitoring.friendly_error(h['error'])}",
                             {"test": h})
    if not h.get("expected_content"):
        return ServiceResult("Web access (HTTP)", "degraded",
                             "A page loaded but not the expected one (captive portal or proxy login?)",
                             {"test": h})
    return ServiceResult("Web access (HTTP)", "ok",
                         f"Test page loaded in {h['ms']} ms", {"test": h})


def run_network_group() -> tuple[list, str]:
    """Run network_check once and split it into three services."""
    raw = network_monitoring.check_network()
    d = raw["details"]
    services = [judge_internet(d), judge_dns(d), judge_http(d)]
    return services, d["summary"]


# --------------------------------------------------------------------------
# External service monitors (./external_monitoring)
# --------------------------------------------------------------------------

EXTERNAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "external_monitoring")

# label -> (module, function). Same functions check_all_services() calls, but
# each is run as its own check so one failing API can't hide the others.
EXTERNAL_SERVICES = {
    "Slack":   ("slack_status",   "get_slack_status"),
    "GitHub":  ("github_status",  "get_github_status"),
    "Dropbox": ("dropbox_status", "get_dropbox_status"),
}

_STATUS_KEYS = ("status", "state", "indicator", "health")
_NAME_KEYS = ("service", "name", "service_name")
_MESSAGE_KEYS = ("message", "description", "summary", "status_description", "details", "error")


def _as_dict(obj) -> dict:
    """ServiceResult -> dict, preferring its own to_dict()."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(vars(obj)) if hasattr(obj, "__dict__") else {"status": obj}


def _first(data: dict, keys: tuple):
    for k in keys:
        if data.get(k) not in (None, ""):
            return data[k]
    return None


def normalize_status(raw) -> str:
    """Map whatever status vocabulary the monitors use onto ok/degraded/down/unknown."""
    if isinstance(raw, bool):
        return "ok" if raw else "down"
    if isinstance(raw, dict):  # e.g. Statuspage: {"indicator": "none", "description": "..."}
        raw = _first(raw, _STATUS_KEYS)
    if raw is None:
        return "unknown"
    text = str(getattr(raw, "value", raw)).strip().lower().replace("_", " ").replace("-", " ")
    if text in ("none", "ok", "up", "online", "healthy", "good", "available", "resolved"):
        return "ok"
    # Check the bad words before "operational" so "not operational" isn't read as ok
    if any(w in text for w in ("major", "critical", "outage", "down", "offline", "fail", "error",
                               "unavailable", "not operational")):
        return "degraded" if "partial" in text else "down"
    if any(w in text for w in ("minor", "degrad", "partial", "warning", "slow", "maintenance",
                               "incident", "issue")):
        return "degraded"
    if "operational" in text or "normal" in text or "all systems" in text:
        return "ok"
    return "unknown"


def make_external_check(label: str, module_name: str, func_name: str):
    def run():
        # Imported here (not at the top) so a missing/broken monitor is caught
        # by the engine and reported as "unknown" instead of crashing it.
        if EXTERNAL_DIR not in sys.path:
            sys.path.insert(0, EXTERNAL_DIR)
        func = getattr(importlib.import_module(module_name), func_name)
        data = _as_dict(func())

        raw_status = _first(data, _STATUS_KEYS)
        state = normalize_status(raw_status)
        components = data.get("affected_components") or []
        incident = bool(data.get("active_incident"))

        # The monitor couldn't reach the status API: we know nothing, so don't guess.
        if data.get("api_success") is False:
            state = "unknown"
        # Headline says Operational, but there is an open incident or a
        # component that isn't operational: not fully functional.
        elif state == "ok" and (incident or components):
            state = "degraded"

        parts = [str(raw_status) if raw_status is not None else "Monitor returned no status field"]
        if data.get("incident_title"):
            parts.append(f"incident: {data['incident_title']}")
        elif incident:
            parts.append("active incident")
        if components:
            parts.append("affected: " + ", ".join(map(str, components)))
        if data.get("maintenance"):
            parts.append("maintenance in progress")
        if data.get("error"):
            parts.append(f"monitor error: {data['error']}")
        generic = _first(data, ("message", "description", "summary", "status_description"))
        if generic:
            parts.append(str(generic))

        return [ServiceResult(label, state, " | ".join(parts), {"raw": data})], ""
    return run


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

class DiagnosticEngine:
    def __init__(self):
        # name -> (function returning (list[ServiceResult], diagnosis_text), timeout seconds)
        self._groups: dict[str, tuple[Callable, int]] = {}

    def register(self, name: str, func: Callable, timeout: int = 60) -> None:
        self._groups[name] = (func, timeout)

    def _run_group(self, name: str, func: Callable, timeout: int):
        """Run one group with a timeout; never let it crash the engine."""
        start = time.perf_counter()
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(func)
        try:
            services, diagnosis = future.result(timeout=timeout)
            return services, diagnosis
        except FutureTimeout:
            msg = f"check group '{name}' timed out after {timeout}s"
        except Exception as e:  # noqa: BLE001 - we want to catch everything here
            msg = f"check group '{name}' crashed: {type(e).__name__}: {e}"
        finally:
            pool.shutdown(wait=False)
        ms = int((time.perf_counter() - start) * 1000)
        return [ServiceResult(name, "unknown", msg, duration_ms=ms)], msg

    def run(self) -> Report:
        start = time.perf_counter()
        all_services, diagnoses = [], []

        with ThreadPoolExecutor(max_workers=max(1, len(self._groups))) as outer:
            futures = {
                name: outer.submit(self._run_group, name, func, timeout)
                for name, (func, timeout) in self._groups.items()
            }
            for name, fut in futures.items():
                services, diagnosis = fut.result()
                all_services.extend(services)
                if diagnosis:
                    diagnoses.append(diagnosis)

        # Overall verdict = the worst individual service state.
        overall = max((s.state for s in all_services), key=lambda s: SEVERITY[s], default="unknown")
        failing = [s for s in all_services if s.state != "ok"]

        if not all_services:
            summary = "No checks were registered."
        elif not failing:
            summary = f"All {len(all_services)} services are functional."
        else:
            names = ", ".join(f"{s.service} ({s.state})" for s in failing)
            summary = f"{len(failing)} of {len(all_services)} services have problems: {names}."

        return Report(
            overall_state=overall,
            all_functional=bool(all_services) and not failing,
            summary=summary,
            services=all_services,
            diagnosis=" ".join(diagnoses),
            total_ms=int((time.perf_counter() - start) * 1000),
        )


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def format_report(report: Report) -> str:
    bar = "=" * 62
    lines = [bar, "  DIAGNOSTIC REPORT", bar, ""]
    verdict = "YES - every service is functional" if report.all_functional \
        else "NO - at least one service is not functional"
    lines += [f"  ALL SERVICES FUNCTIONAL?  {verdict}",
              f"  {report.summary}", ""]
    if report.diagnosis and not report.all_functional:
        lines += [f"  Likely cause: {report.diagnosis}", ""]

    lines.append("  SERVICE STATUS")
    for s in report.services:
        lines.append(f"    {LABELS[s.state]}  {s.service:<20} {s.summary}")
        # Show the individual failing tests so the cause is visible
        for t in s.details.get("tests", []):
            if not t["ok"]:
                target = t.get("target") or t.get("name")
                lines.append(f"              - {target}: {network_monitoring.friendly_error(t['error'])}")
    lines += ["", f"  Completed in {report.total_ms} ms", bar]
    return "\n".join(lines)


def main() -> int:
    engine = DiagnosticEngine()
    engine.register("network", run_network_group, timeout=60)
    for label, (module_name, func_name) in EXTERNAL_SERVICES.items():
        engine.register(label, make_external_check(label, module_name, func_name), timeout=30)
    # Add more groups here, e.g.:
    # engine.register("disk", run_disk_group)   # must return (list[ServiceResult], diagnosis_str)

    report = engine.run()

    if "--json" in sys.argv:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(format_report(report))
    return EXIT_CODES[report.overall_state]


if __name__ == "__main__":
    sys.exit(main())
