from __future__ import annotations
import os
from typing import List, Dict

# Google API imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Gmail read-only scope: safest option
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """
    Handles Gmail authentication.
    - Looks for token.json (cached login)
    - If missing/expired, uses credentials.json to open a browser login
    - Saves refreshed token to token.json
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "⚠️ credentials.json missing! Download it from Google Cloud Console "
                    "and place it in the project root."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def list_unread_emails(service, max_results: int = 10) -> List[Dict]:
    """
    Fetches the last `max_results` unread emails (date, from, subject)
    """
    results = service.users().messages().list(
        userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        emails.append({
            "date": headers.get("Date", ""),
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(no subject)"),
        })

    return emails


def main():
    print("🔐 Connecting to Gmail (read-only)…")
    service = get_gmail_service()
    emails = list_unread_emails(service, max_results=10)

    if not emails:
        print("✅ No unread emails 🎉")
        return

    print("\n📬 Your latest unread emails:")
    for e in emails:
        print(f"- {e['date']} | {e['from']} — {e['subject']}")

    print("\n✅ Gmail connection working! Next: saving locally.")


if __name__ == "__main__":
    main()
