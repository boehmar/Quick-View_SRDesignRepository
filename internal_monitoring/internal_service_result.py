from dataclasses import dataclass, asdict
from typing import Optional


# This class defines the standard result format that every internal service monitor will use
@dataclass
class InternalServiceResult:

    # Name of the internal service being checked
    service_name: str

    # Hostname used for DNS testing
    hostname: str

    # URL used for the HTTP or HTTPS test
    url: str

    # True if the hostname successfully resolves
    dns_success: bool

    # True if the HTTP or HTTPS request succeeds
    http_success: bool

    # HTTP status code returned by the service
    # None is used when no response is received
    status_code: Optional[int]

    # Response time of the service in milliseconds
    # None is used when no response is received
    response_time_ms: Optional[float]

    # True if the service is considered available
    available: bool

    # Time when the service was checked
    checked_at: str

    # Stores an error message if a test fails
    # None is used when there is no error
    error: Optional[str] = None


    # Converts the InternalServiceResult object into a dictionary
    # This makes it easier to send the data to other parts of the project later
    def to_dict(self):
        return asdict(self)