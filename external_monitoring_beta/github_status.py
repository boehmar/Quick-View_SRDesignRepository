"""
Connects to a public, no-login status API (GitHub's Statuspage feed) and
reports overall health plus any component that is not fully operational.

Install:  pip install requests
Run:      python github_status_check.py

Many SaaS vendors use the same Statuspage JSON format, so you can point
BASE_URL at another one (e.g. https://status.atlassian.com) with no other changes.
"""

import json
import sys

import requests

BASE_URL = "https://www.githubstatus.com/api/v2"

# Statuspage "indicator" values -> our states
INDICATOR_TO_STATE = {
    "none": "ok",
    "minor": "degraded",
    "major": "down",
    "critical": "down",
}


def check_github() -> dict:
    try:
        overall = requests.get(f"{BASE_URL}/status.json", timeout=10)
        overall.raise_for_status()
        components = requests.get(f"{BASE_URL}/components.json", timeout=10)
        components.raise_for_status()
    except requests.RequestException as e:
        return {"name": "GitHub", "state": "unknown",
                "details": {"error": f"Could not reach status API: {e}"}}

    status = overall.json()["status"]
    problems = [
        {"component": c["name"], "status": c["status"]}
        for c in components.json()["components"]
        if c["status"] != "operational"
    ]

    return {
        "name": "GitHub",
        "state": INDICATOR_TO_STATE.get(status["indicator"], "unknown"),
        "details": {
            "description": status["description"],
            "components_with_issues": problems,
            "response_ms": int(overall.elapsed.total_seconds() * 1000),
        },
    }


if __name__ == "__main__":
    result = check_github()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["state"] == "ok" else 1)
