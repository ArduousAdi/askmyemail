from __future__ import annotations
import os, json, argparse, time
from typing import List, Dict
from datetime import timezone
from pathlib import Path

from dateutil import parser as dateparser, tz
from dotenv import load_dotenv
import google.generativeai as genai

# Gmail imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Silence gRPC debug logs (Gemini SDK internal)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_LOG_SEVERITY_LEVEL"] = "ERROR"

# Gmail read-only scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Load environment (.env) and set Gemini key and
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("⚠️ GEMINI_API_KEY not set. Add it to your .env file.")
else:
    genai.configure(api_key=GEMINI_API_KEY)


# ----------------------------------------------------------
# 1️⃣  Gmail Authentication
# ----------------------------------------------------------
def get_gmail_service():
    """Authenticate user via OAuth, return Gmail API service."""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError(
                    "⚠️ Missing credentials.json! Download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ----------------------------------------------------------
# 2️⃣  Fetch unread emails
# ----------------------------------------------------------
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


# ----------------------------------------------------------
# 3️⃣  Save emails locally for memory
# ----------------------------------------------------------
def save_emails_to_json(emails: List[Dict], filename: str = "emails.json"):
    """Save fetched emails locally to avoid refetching every time."""
    if not emails:
        print("📭 No new emails to save.")
        return

    if os.path.exists(filename):
        with open(filename, "r") as f:
            old_data = json.load(f)
    else:
        old_data = []

    new_emails = [e for e in emails if e["id"] not in {d["id"] for d in old_data}]
    if not new_emails:
        print("✅ All emails already saved.")
        return

    combined = old_data + new_emails
    with open(filename, "w") as f:
        json.dump(combined, f, indent=2)

    print(f"💾 Saved {len(new_emails)} new emails to {filename}")


# ----------------------------------------------------------
# 4️⃣  Load + Filter saved emails
# ----------------------------------------------------------
def load_saved_emails(filename: str = "emails.json"):
    """Load previously saved emails."""
    if not os.path.exists(filename):
        return []
    with open(filename, "r") as f:
        return json.load(f)


def filter_emails(
    emails,
    since: str | None = None,
    from_contains: str | None = None,
    subject_contains: str | None = None,
):
    """Filter emails by date, sender, or subject."""
    out = emails

    def to_utc_aware(dt):
        if not dt:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if since:
        try:
            since_dt = dateparser.parse(since)
        except Exception:
            since_dt = None

        if since_dt:
            since_dt = to_utc_aware(since_dt)

            def _to_dt(e):
                try:
                    return to_utc_aware(dateparser.parse(e.get("date", "")))
                except Exception:
                    return None

            out = [e for e in out if (_to_dt(e) and _to_dt(e) >= since_dt)]

    if from_contains:
        s = from_contains.lower()
        out = [e for e in out if s in e.get("from", "").lower()]

    if subject_contains:
        s = subject_contains.lower()
        out = [e for e in out if s in e.get("subject", "").lower()]

    return out


# ----------------------------------------------------------
# 5️⃣  Summarization (optimized for speed)
# ----------------------------------------------------------
def summarize_emails_with_gemini(emails, title="Summary of selected emails"):
    """Summarize email subjects quickly using Gemini Flash."""
    if not emails:
        return "No emails matched your filters."

    # Limit how much data we send to Gemini for faster output
    bullet_lines = [
        f"- {e.get('date','')[:25]} | {e.get('from','')[:60]} | {e.get('subject','')[:140]}"
        for e in emails[:50]
    ]
    digest = "\n".join(bullet_lines)[:8000]

    prompt = f"""
You are an executive assistant.
Summarize the following email headers into:
1) 5–8 concise bullet points describing main themes.
2) A short 'Action Items' checklist (✅ style).
3) Group related emails if possible.

Emails:
{digest}
"""

    model = genai.GenerativeModel("gemini-1.5-flash")
    try:
        resp = model.generate_content(prompt)
        return resp.text.strip() if resp and resp.text else "No summary generated."
    except Exception as e:
        return f"⚠️ Gemini summarization failed: {e}"


# ----------------------------------------------------------
# 6️⃣  CLI and Orchestration
# ----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="AskMyEmail — fetch & summarize Gmail")
    parser.add_argument("--fetch", action="store_true", help="Fetch unread emails and save to emails.json")
    parser.add_argument("--max", type=int, default=10, help="Max unread emails to fetch")
    parser.add_argument("--since", type=str, default=None, help='Filter saved emails since (e.g. "2025-10-01")')
    parser.add_argument("--from-contains", type=str, default=None, help="Filter by sender substring")
    parser.add_argument("--subject-contains", type=str, default=None, help="Filter by subject substring")
    parser.add_argument("--summary", action="store_true", help="Summarize filtered emails with Gemini")

    args = parser.parse_args()

    # --- Step 1: Fetch from Gmail ---
    if args.fetch:
        print("🔐 Connecting to Gmail (read-only)…")
        service = get_gmail_service()
        emails = list_unread_emails(service, max_results=args.max)

        if not emails:
            print("✅ No unread emails 🎉")
        else:
            print("\n📬 Latest unread emails:")
            for e in emails:
                print(f"- {e['date']} | {e['from']} — {e['subject']}")
        save_emails_to_json(emails)

    # --- Step 2: Filter ---
    saved = load_saved_emails()
    filtered = filter_emails(
        saved,
        since=args.since,
        from_contains=args.from_contains,
        subject_contains=args.subject_contains,
    )

    print(f"\n📂 {len(filtered)} emails selected for analysis.")

    # --- Step 3: Summarize ---
    if args.summary:
        print("\n🧠 Generating summary with Gemini (1.5-flash)…")
        summary = summarize_emails_with_gemini(filtered)
        print("\n" + summary + "\n")

        # Save to summary.md
        # --- Save summary to project root, no matter where you ran the script from
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    OUT_PATH = PROJECT_ROOT / "summary.md"

    try:
        text = summary if (summary and summary.strip()) else "No summary generated."
        OUT_PATH.write_text(text, encoding="utf-8")
        print(f"📝 Summary saved to: {OUT_PATH}")
    except Exception as e:
        print(f"⚠️ Failed to write summary: {e}")
        print(f"cwd was: {os.getcwd()}  | intended path: {OUT_PATH}")




if __name__ == "__main__":
    main()
