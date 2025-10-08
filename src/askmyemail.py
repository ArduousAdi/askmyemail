from __future__ import annotations
import os, json
from typing import List, Dict

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError("⚠️ Missing credentials.json!")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def list_unread_emails(service, max_results: int = 10) -> List[Dict]:
    """Fetch last N unread emails."""
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
            "id": m["id"],
            "date": headers.get("Date", ""),
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", "(no subject)"),
        })

    return emails


def save_emails_to_json(emails: List[Dict], filename: str = "emails.json"):
    """Save fetched emails locally so the app has memory."""
    if not emails:
        print("📭 No new emails to save.")
        return

    # Load existing data if file exists
    if os.path.exists(filename):
        with open(filename, "r") as f:
            old_data = json.load(f)
    else:
        old_data = []

    # Avoid duplicates by checking IDs
    new_emails = [e for e in emails if e["id"] not in {d["id"] for d in old_data}]
    if not new_emails:
        print("✅ All emails already saved.")
        return

    combined = old_data + new_emails
    with open(filename, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"💾 Saved {len(new_emails)} new emails to {filename}")


def main():
    print("🔐 Connecting to Gmail (read-only)…")
    service = get_gmail_service()
    emails = list_unread_emails(service, max_results=10)

    if not emails:
        print("✅ No unread emails 🎉")
        return

    print("\n📬 Latest unread emails:")
    for e in emails:
        print(f"- {e['date']} | {e['from']} — {e['subject']}")

    save_emails_to_json(emails)


if __name__ == "__main__":
    main()
