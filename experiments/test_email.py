import base64
from email.mime.text import MIMEText

from apiclient import errors
from googleapiclient.discovery import build

import google_tools.general


# isort: split
# pylint: disable-next=wrong-import-order
import gitlab_config_personal as config


def create_message(sender, to, subject, message_text):
    """Create a message for an email.
    Args:
        sender: Email address of the sender.
        to: Email address of the receiver.
        subject: The subject of the email message.
        message_text: The text of the email message.
    Returns:
        An object containing a base64url encoded email object.
    """
    message = MIMEText(message_text)
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    message_as_string = message.as_string()
    return {"raw": base64.urlsafe_b64encode(message_as_string.encode()).decode()}


def send_message(service, user_id, message):
    """Send an email message.
    Args:
        service: Authorized Gmail API service instance.
        user_id: User's email address. The special value "me"
        can be used to indicate the authenticated user.
        message: Message to be sent.
    Returns:
        Sent Message.
    """
    try:
        message = (
            service.users().messages().send(userId=user_id, body=message).execute()
        )
        print("Message Id: " + message["id"])
        return message
    except errors.HttpError as error:
        print("An error occurred: " + error)
        return None


# Email variables. Modify this!
EMAIL_FROM = "lab-grading-bot@chalmers-data-structures.iam.gserviceaccount.com"
EMAIL_TO = "REDACTED_EMAIL"
EMAIL_SUBJECT = "Subject"
EMAIL_CONTENT = "Content"


def test():
    creds = google_tools.general.get_token_for_scopes(
        scopes=["https://mail.google.com/"],
        credentials=config.google_credentials_path,
        prefix_url=False,
    )
    service = build("gmail", "v1", credentials=creds)

    message = create_message(EMAIL_FROM, EMAIL_TO, EMAIL_SUBJECT, EMAIL_CONTENT)
    return send_message(service, "me", message)


test()
