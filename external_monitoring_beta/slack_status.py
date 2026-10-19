import requests
from datetime import datetime


# URL for Slack's public status API
SLACK_STATUS_URL = "https://slack-status.com/api/v2.0.0/current"


# Main function that checks Slack's current service status
def get_slack_status():
    try:
        # Send a request to the Slack status API
        # timeout=10 prevents the program from waiting forever
        response = requests.get(SLACK_STATUS_URL, timeout=10)

        # Raise an error if Slack returns a bad HTTP status code
        response.raise_for_status()

        # Convert the JSON response into a Python dictionary
        data = response.json()

        # Get the list of active incidents
        # If there are none, use an empty list
        incidents = data.get("active_incidents", [])

        # Create an empty list for affected Slack components
        affected_components = []

        # Loop through each active incident
        for incident in incidents:

            # Get the affected Slack services for that incident
            for service in incident.get("services", []):

                # Only add the service if it is not already in the list
                if service not in affected_components:
                    affected_components.append(service)

        # Set default values
        # These will be used when Slack has no active incidents
        status = "Operational"
        maintenance = False
        incident_title = None

        # Only run this section if there is at least one active incident
        if incidents:

            # Get the first active incident
            first_incident = incidents[0]

            # Get the title of the incident
            incident_title = first_incident.get("title")

            # Get the incident type and status
            # Convert them to lowercase to make comparisons easier
            incident_type = first_incident.get("type", "").lower()
            incident_status = first_incident.get("status", "").lower()

            # Check if the incident is scheduled maintenance
            if incident_status == "scheduled":
                status = "Maintenance"
                maintenance = True

            # Check if Slack reports an outage
            elif incident_type == "outage":
                status = "Major Outage"

            # If there is an incident but it is not a major outage mark the service as degraded
            else:
                status = "Degraded"

        # Return the Slack information in our standard format
        return {
            "service_name": "Slack",
            "status": status,
            "active_incident": len(incidents) > 0,
            "incident_title": incident_title,
            "affected_components": affected_components,
            "maintenance": maintenance,
            "api_success": True,
            "checked_at": datetime.now().isoformat()
        }

    # Handle problems such as no internet connection, timeout errors, or failed HTTP requests
    except requests.RequestException as error:

        # Return an Unknown status instead of saying Slack is down
        return {
            "service_name": "Slack",
            "status": "Unknown",
            "active_incident": False,
            "incident_title": None,
            "affected_components": [],
            "maintenance": False,
            "api_success": False,
            "checked_at": datetime.now().isoformat(),
            "error": str(error)
        }


# This section only runs when this file is executed directly
if __name__ == "__main__":

    # Call the Slack status function
    result = get_slack_status()

    # Print the result in the terminal
    print(result)