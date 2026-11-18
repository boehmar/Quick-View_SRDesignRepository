from datetime import datetime
import time
from flask import Flask, jsonify
from flask_cors import CORS
import psutil
import requests

app = Flask(__name__)
CORS(app)


GITHUB_URL = "https://www.githubstatus.com/api/v2"
SLACK_URL = "https://slack-status.com/api/v2.0.0/current"
DROPBOX_URL = "https://status.dropbox.com/api/v2/summary.json"


VPN_KEYWORDS = [
    "nord",
    "wireguard",
    "openvpn",
    "warp",
    "tailscale",
    "tap",
    "wintun",
]


def check_github():
    try:
        res = requests.get(f"{GITHUB_URL}/status.json", timeout=6)
        res.raise_for_status()
        comp_res = requests.get(f"{GITHUB_URL}/components.json", timeout=6)
        comp_res.raise_for_status()

        status_info = res.json().get("status", {})
        indicator = status_info.get("indicator", "none").lower()

        status_map = {
            "none": "Operational",
            "minor": "Degraded",
            "major": "Partial Outage",
            "critical": "Major Outage",
        }
        status = status_map.get(indicator, "Unknown")

        
        affected = []
        for comp in comp_res.json().get("components", []):
            if comp.get("status") != "operational":
                affected.append(comp.get("name"))

        return {
            "service_name": "GitHub",
            "status": status,
            "description": status_info.get(
                "description", "All Systems Operational"
            ),
            "affected": affected,
            "latency": int(res.elapsed.total_seconds() * 1000),
            "online": True,
        }
    except Exception as e:
        return {
            "service_name": "GitHub",
            "status": "Unknown",
            "description": f"Error reaching GitHub: {e}",
            "affected": [],
            "latency": None,
            "online": False,
        }


def check_slack():
    try:
        res = requests.get(SLACK_URL, timeout=8)
        res.raise_for_status()
        data = res.json()

        incidents = data.get("active_incidents", [])
        affected = []
        for inc in incidents:
            for srv in inc.get("services", []):
                if srv not in affected:
                    affected.append(srv)

        status = "Operational"
        desc = "All Slack services are running normally."

        if incidents:
            first = incidents[0]
            desc = first.get("title", "Active incident reported")
            inc_type = first.get("type", "").lower()
            inc_status = first.get("status", "").lower()

            if inc_status == "scheduled":
                status = "Maintenance"
            elif inc_type == "outage":
                status = "Major Outage"
            else:
                status = "Degraded"

        return {
            "service_name": "Slack",
            "status": status,
            "description": desc,
            "affected": affected,
            "latency": int(res.elapsed.total_seconds() * 1000),
            "online": True,
        }
    except Exception as e:
        return {
            "service_name": "Slack",
            "status": "Unknown",
            "description": f"Error reaching Slack: {e}",
            "affected": [],
            "latency": None,
            "online": False,
        }


def check_dropbox():
    try:
        res = requests.get(DROPBOX_URL, timeout=8)
        res.raise_for_status()
        data = res.json()

        indicator = data.get("status", {}).get("indicator", "").lower()
        incidents = data.get("incidents", [])
        components = data.get("components", [])
        maintenance = data.get("scheduled_maintenances", [])

        status_map = {
            "none": "Operational",
            "minor": "Degraded",
            "major": "Partial Outage",
            "critical": "Major Outage",
        }
        status = status_map.get(indicator, "Unknown")

        affected = []
        for comp in components:
            if comp.get("status", "").lower() != "operational":
                affected.append(comp.get("name"))

        
        for m in maintenance:
            if m.get("status", "").lower() == "in_progress":
                if status == "Operational":
                    status = "Maintenance"
                break

        desc = (
            incidents[0].get("name")
            if incidents
            else "Dropbox services are operational."
        )

        return {
            "service_name": "Dropbox",
            "status": status,
            "description": desc,
            "affected": affected,
            "latency": int(res.elapsed.total_seconds() * 1000),
            "online": True,
        }
    except Exception as e:
        return {
            "service_name": "Dropbox",
            "status": "Unknown",
            "description": f"Error reaching Dropbox: {e}",
            "affected": [],
            "latency": None,
            "online": False,
        }


def check_local_network():
    flagged_vpns = []
    for adapter_name in psutil.net_if_addrs().keys():
        for word in VPN_KEYWORDS:
            if word in adapter_name.lower():
                flagged_vpns.append(adapter_name)

    start_time = time.time()
    try:
        requests.get("https://1.1.1.1", timeout=3)
        ping_ms = int((time.time() - start_time) * 1000)
        connected = True
    except Exception:
        ping_ms = None
        connected = False

    if flagged_vpns:
        status = "Major Outage"
        desc = (
            f"Warning: Unauthorized VPN adapter found ({', '.join(flagged_vpns)})."
        )
    elif not connected:
        status = "Major Outage"
        desc = "No internet connection. Cannot reach external gateway."
    elif ping_ms and ping_ms > 400:
        status = "Degraded"
        desc = f"High network latency detected ({ping_ms}ms)."
    else:
        status = "Operational"
        desc = "Local network adapter is healthy and no VPN tunnels detected."

    return {
        "service_name": "Local Network & VPN",
        "status": status,
        "description": desc,
        "affected": flagged_vpns,
        "latency": ping_ms,
        "online": True,
    }


@app.route("/api/status")
def get_all_status():
    results = [
        check_github(),
        check_slack(),
        check_dropbox(),
        check_local_network(),
    ]
    return jsonify({
        "services": results,
        "last_checked": datetime.now().strftime("%I:%M:%S %p"),
    })


if __name__ == "__main__":
    app.run(port=5000, debug=True)