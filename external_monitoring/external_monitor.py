# Import each external service monitoring function
from slack_status import get_slack_status
from github_status import get_github_status
from dropbox_status import get_dropbox_status


# Main function that checks all external services
def check_all_services():

    # Create an empty list to store each service result
    results = []

    # Check Slack's current status
    slack_result = get_slack_status()
    results.append(slack_result)

    # Check GitHub's current status
    github_result = get_github_status()
    results.append(github_result)

    # Check Dropbox's current status
    dropbox_result = get_dropbox_status()
    results.append(dropbox_result)

    # Return all service results in one list
    return results


# This section only runs when this file is executed directly
if __name__ == "__main__":

    # Check all external services
    results = check_all_services()

    # Loop through each ServiceResult
    for result in results:

        # Convert the ServiceResult into a dictionary and print it in the terminal
        print(result.to_dict())