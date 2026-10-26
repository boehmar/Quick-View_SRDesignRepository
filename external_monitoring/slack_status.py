import requests
from datetime import datetime

# Import the standard result format used by all external services
from service_result import ServiceResult


# URL for the public service status API
SLACK_STATUS_URL = "https://slack-status.com/api/v2.0.0/current"


# Main function that checks the current service status
def get_slack_status():
    try:
        # Send a request to the service status API
        # timeout=10 prevents the program from waiting forever
        response = requests.get(SLACK_STATUS_URL, timeout=10)

        # Raise an error if the service returns a bad HTTP status code
        response.raise_for_status()

        # Convert the JSON response into a Python dictionary
        data = response.json()

        # Get the list of active incidents
        # If there are none, use an empty list
        incidents = data.get("active_incidents", [])

        # Create an empty list for affected service components
        affected_components = []

        # Loop through each active incident
        for incident in incidents:

            # Get the affected services for the incident
            for service in incident.get("services", []):

                # Do not add the same service more than once
                if service not in affected_components:
                    affected_components.append(service)

        # Default values if there are no active incidents
        status = "Operational"
        maintenance = False
        incident_title = None

        # Check active incident information
        if incidents:

            # Get the first active incident
            first_incident = incidents[0]

            # Get the title of the incident
            incident_title = first_incident.get("title")

            # Get the incident type and status
            incident_type = first_incident.get("type", "").lower()
            incident_status = first_incident.get("status", "").lower()

            # Check for scheduled maintenance
            if incident_status == "scheduled":
                status = "Maintenance"
                maintenance = True

            # Check for an outage
            elif incident_type == "outage":
                status = "Major Outage"

            # Otherwise treat the incident as degraded service
            else:
                status = "Degraded"

        # Return the service information using the standard ServiceResult format
        return ServiceResult(
            service_name="Slack",
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
            service_name="Slack",
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
    result = get_slack_status()

    # Convert the ServiceResult into a dictionary and print it in the terminal
    print(result.to_dict())