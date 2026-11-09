from dataclasses import dataclass, asdict


# This class defines the standard profile format that every internal service will use
@dataclass
class ServiceProfile:

    # Name of the internal service
    service_name: str

    # Hostname used for DNS testing
    hostname: str

    # URL used for the HTTP or HTTPS test
    url: str

    # Maximum number of seconds to wait for a response
    timeout: int = 10


    # Converts the ServiceProfile object into a dictionary
    # This makes it easier to store or display the profile later
    def to_dict(self):
        return asdict(self)