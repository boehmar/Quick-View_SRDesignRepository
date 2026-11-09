import socket
import requests
from datetime import datetime
from time import perf_counter

# Import the standard result format used by all internal services
from internal_service_result import InternalServiceResult

# Import the standard profile format used by all internal services
from service_profile import ServiceProfile


# Main function that checks the current internal service status
def check_internal_service(profile: ServiceProfile):

    # Set default values
    # These will be updated as each test is completed
    dns_success = False
    http_success = False
    status_code = None
    response_time_ms = None
    available = False
    error = None

    try:
        # Try to resolve the hostname using DNS
        socket.gethostbyname(profile.hostname)

        # Mark the DNS test as successful
        dns_success = True

    # Handle problems with DNS resolution
    except socket.gaierror as dns_error:

        # Store the DNS error message
        error = f"DNS resolution failed: {dns_error}"

        # Return the service information in our standard format
        return InternalServiceResult(
            service_name=profile.service_name,
            hostname=profile.hostname,
            url=profile.url,
            dns_success=dns_success,
            http_success=http_success,
            status_code=status_code,
            response_time_ms=response_time_ms,
            available=available,
            checked_at=datetime.now().isoformat(),
            error=error
        )

    try:
        # Record the starting time of the HTTP request
        start_time = perf_counter()

        # Send a request to the internal service
        # timeout prevents the program from waiting forever
        response = requests.get(
            profile.url,
            timeout=profile.timeout
        )

        # Record the ending time of the HTTP request
        end_time = perf_counter()

        # Calculate the response time in milliseconds
        response_time_ms = round(
            (end_time - start_time) * 1000,
            2
        )

        # Store the HTTP status code
        status_code = response.status_code

        # Mark the HTTP request as successful
        http_success = True

        # Consider the service available if the response status code is between 200 and 399
        available = 200 <= status_code < 400

        # Store an error if the service responded but returned an unsuccessful status code
        if not available:
            error = f"Service returned HTTP status {status_code}"

    # Handle connection problems, timeouts, and failed HTTP requests
    except requests.RequestException as request_error:

        # Store the HTTP request error message
        error = str(request_error)

    # Return the service information in our standard format
    return InternalServiceResult(
        service_name=profile.service_name,
        hostname=profile.hostname,
        url=profile.url,
        dns_success=dns_success,
        http_success=http_success,
        status_code=status_code,
        response_time_ms=response_time_ms,
        available=available,
        checked_at=datetime.now().isoformat(),
        error=error
    )


# This section only runs when this file is executed directly
if __name__ == "__main__":

    # Create a test service profile
    test_profile = ServiceProfile(
        service_name="Test Service",
        hostname="example.com",
        url="https://example.com",
        timeout=10
    )

    # Check the test service
    result = check_internal_service(test_profile)

    # Convert the InternalServiceResult into a dictionary and print it in the terminal
    print(result.to_dict())