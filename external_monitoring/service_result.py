from dataclasses import dataclass, asdict
from typing import Optional


# This class defines the standard result format that every external service monitor will use
@dataclass
class ServiceResult:

    # Name of the service being checked
    service_name: str

    # Current status of the service
    # Examples: Operational, Degraded, Major Outage, Unknown
    status: str

    # True if the service currently has an active incident
    active_incident: bool

    # Title of the active incident
    # None is used when there is no incident
    incident_title: Optional[str]

    # List of service components affected by an incident
    affected_components: list[str]

    # True if scheduled maintenance is currently happening
    maintenance: bool

    # True if our program successfully contacted the status API
    api_success: bool

    # Time when the service was checked
    checked_at: str

    # Stores an error message if the API request fails
    # None is used when there is no error
    error: Optional[str] = None


    # Converts the ServiceResult object into a dictionary
    def to_dict(self):
        return asdict(self)