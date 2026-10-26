import requests
from datetime import datetime

# Import the standard result format used by all external services
from service_result import ServiceResult


# URL for the public service status API
DROPBOX_STATUS_URL = "https://status.dropbox.com/api/v2/summary.json"


# Main function that checks the current service status
def get_dropbox_status():
    try:
        # Send a request to the service status API
        response = requests.get(DROPBOX_STATUS_URL, timeout=10)

        # Raise an error if the service returns a bad HTTP status code
        response.raise_for_status()

        # Convert the JSON response into a Python dictionary
        data = response.json()

        # Get the overall service status information
        status_data = data.get("status", {})
        indicator = status_data.get("indicator", "").lower()

        # Get the list of active incidents
        incidents = data.get("incidents", [])

        # Get the service components
        components = data.get("components", [])

        # Get scheduled maintenance information
        scheduled_maintenance = data.get("scheduled_maintenances", [])

        # Convert the service status indicator into our standard status format
        status_map = {
            "none": "Operational",
            "minor": "Degraded",
            "major": "Partial Outage",
            "critical": "Major Outage"
        }

        # Use Unknown if the service returns an unexpected indicator
        status = status_map.get(indicator, "Unknown")

        # Create a list of components that are not operating normally
        affected_components = []

        for component in components:
            component_status = component.get("status", "").lower()

            if component_status != "operational":
                affected_components.append(component.get("name"))

        # Get the first active incident title if one exists
        incident_title = None

        if incidents:
            incident_title = incidents[0].get("name")

        # Check if scheduled maintenance is currently happening
        maintenance = False

        for maintenance_event in scheduled_maintenance:
            if maintenance_event.get("status", "").lower() == "in_progress":
                maintenance = True
                break

        # If maintenance is happening and there is no outage, display Maintenance as the overall status
        if maintenance and status == "Operational":
            status = "Maintenance"

        # Return the service information using the standard ServiceResult format
        return ServiceResult(
            service_name="Dropbox",
            status=status,
            active_incident=len(incidents) > 0,
            incident_title=incident_title,
            affected_components=affected_components,
            maintenance=maintenance,
            api_success=True,
            checked_at=datetime.now().isoformat(),
            error=None
        )

    # Handle connection problems, timeouts, and failed HTTP requests
    except requests.RequestException as error:

        # Return Unknown instead of assuming the service is down
        return ServiceResult(
            service_name="Dropbox",
            status="Unknown",
            active_incident=False,
            incident_title=None,
            affected_components=[],
            maintenance=False,
            api_success=False,
            checked_at=datetime.now().isoformat(),
            error=str(error)
        )


# This section only runs when this file is executed directly
if __name__ == "__main__":

    # Get the current service status
    result = get_dropbox_status()

    # Convert the ServiceResult into a dictionary and print it in the terminal
    print(result.to_dict())