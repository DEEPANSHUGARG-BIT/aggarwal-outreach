"""
Aggarwal Electric Company — Automated Vendor Empanelment Outreach
=================================================================
Reads prospects from prospects.csv (exported from Apollo website).
Sends fixed email template + catalogue link via Gmail.
Tracks everything in outreach_tracker.csv.
Handles follow-ups at Day 5 and Day 10 if no reply.
"""

import os
import csv
import time
import base64
import logging
import pickle
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SENDER_EMAIL         = os.environ.get("SENDER_EMAIL", "aggelectric@gmail.com")
SENDER_NAME          = os.environ.get("SENDER_NAME", "Deepanshu Garg")
CATALOGUE_LINK       = os.environ.get("CATALOGUE_LINK", "YOUR_GOOGLE_DRIVE_LINK")
GMAIL_CREDENTIALS    = "gmail_credentials.json"
GMAIL_TOKEN_FILE     = "gmail_token.pickle"
PROSPECTS_CSV        = "prospects.csv"       # you upload this from Apollo export
TRACKER_CSV          = "outreach_tracker.csv"  # auto-created, tracks all sends

# Rate limits
EMAILS_PER_DAY       = 15
DELAY_BETWEEN_EMAILS = 60    # seconds between each send
FOLLOW_UP_1_DAYS     = 5
FOLLOW_UP_2_DAYS     = 10

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler("outreach.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# ─── GREETING ────────────────────────────────────────────────────────────────

def build_greeting(first_name: str, email: str) -> str:
    generic = ("info", "contact", "admin", "sales", "purchase", "procurement",
               "hr", "office", "enquiry", "query", "support", "hello", "mail")
    local = email.split("@")[0].lower()
    if first_name and not any(local.startswith(g) for g in generic):
        return f"Dear {first_name},"
    return "Dear Sir/Ma'am,"

# ─── EMAIL TEMPLATES ─────────────────────────────────────────────────────────

SUBJECT = "Vendor Empanelment Request – Aggarwal Electric Company"

def get_initial_body(first_name, email):
    return f"""{build_greeting(first_name, email)}

I would like to introduce Aggarwal Electric Company (Estd. 1995), based in India — an authorized distributor of Polycab Wires & Cables and authorized dealer for Bajaj, Crompton, Anchor, Panasonic, Dowell's, GreatWhite, and many more leading brands.

Please find our company profile and product catalogue here:
{CATALOGUE_LINK}

Why Choose Us:
- Authorized & Genuine Products
- Wide Product Range Under One Roof
- Competitive Prices & Ready Stock
- 30+ Years of Industry Trust

We would like to register as an approved vendor with your esteemed organization. Kindly guide us through the vendor empanelment process and share the required documentation.

We assure you of the best quality, reliable supply, and prompt service at all times.

--
Best Regards,
Deepanshu Garg
Aggarwal Electric Company | Estd. 1995
Mobile: +91 92052 10416
Website: www.aggarwalelectric.com
Office: Narela Road, Piou Manyari, Kundli, Sonipat, Haryana 131028
Warehouse: Killa No-56/2 Wazidpur Saboli, Sonipat, Haryana 131029

---
To unsubscribe from future emails, reply with "Unsubscribe" in the subject line.
"""

def get_followup1_body(first_name, email):
    return f"""{build_greeting(first_name, email)}

I hope you are doing well. I am following up on my earlier email regarding vendor empanelment for Aggarwal Electric Company.

In case my previous email got missed, we are an authorized distributor of Polycab Wires & Cables and dealer for Bajaj, Crompton, Anchor, Panasonic, Dowell's, GreatWhite, and many more brands.

You can view our product catalogue here:
{CATALOGUE_LINK}

We would be glad to be registered as an approved vendor with your organization. Please let us know the process or documentation required and we will promptly comply.

--
Best Regards,
Deepanshu Garg
Aggarwal Electric Company | Estd. 1995
Mobile: +91 92052 10416
Website: www.aggarwalelectric.com

---
To unsubscribe, reply with "Unsubscribe" in the subject line.
"""

def get_followup2_body(first_name, email):
    return f"""{build_greeting(first_name, email)}

I am writing for the last time regarding our vendor empanelment request for Aggarwal Electric Company.

We understand you may be busy and we respect your time completely. Should your organization ever require reliable electrical products — wires & cables, switchgear, lighting, earthing, or industrial accessories — from trusted brands like Polycab, Bajaj, Crompton, Anchor, and Panasonic, please do consider us.

Our catalogue is available here for future reference:
{CATALOGUE_LINK}

Thank you for your time and we wish your organization continued success.

--
Best Regards,
Deepanshu Garg
Aggarwal Electric Company | Estd. 1995
Mobile: +91 92052 10416
Website: www.aggarwalelectric.com

---
To unsubscribe, reply with "Unsubscribe" in the subject line.
"""

# ─── PROSPECTS CSV ───────────────────────────────────────────────────────────

def load_prospects() -> list:
    """
    Load prospects from Apollo CSV export.
    Apollo exports with columns like:
    First Name, Last Name, Title, Company, Email, ...
    We try multiple column name formats to be safe.
    """
    if not Path(PROSPECTS_CSV).exists():
        log.warning(f"No {PROSPECTS_CSV} found — nothing to send.")
        return []

    prospects = []
    with open(PROSPECTS_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try multiple possible column names from Apollo export
            email = (
                row.get("Email") or row.get("email") or
                row.get("Work Email") or row.get("work_email") or ""
            ).strip().lower()

            if not email or "@" not in email:
                continue

            first_name = (
                row.get("First Name") or row.get("first_name") or
                row.get("FirstName") or ""
            ).strip()

            last_name = (
                row.get("Last Name") or row.get("last_name") or
                row.get("LastName") or ""
            ).strip()

            company = (
                row.get("Company") or row.get("company") or
                row.get("Organization") or row.get("Account Name") or ""
            ).strip()

            title = (
                row.get("Title") or row.get("title") or
                row.get("Job Title") or row.get("job_title") or ""
            ).strip()

            prospects.append({
                "email":      email,
                "first_name": first_name,
                "last_name":  last_name,
                "company":    company,
                "title":      title,
            })

    log.info(f"Loaded {len(prospects)} prospects from {PROSPECTS_CSV}")
    return prospects

# ─── TRACKER CSV ─────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "email", "first_name", "last_name", "company", "title",
    "status", "initial_sent_date", "followup1_date", "followup2_date",
    "replied", "unsubscribed", "last_updated"
]

def load_tracker() -> dict:
    if not Path(TRACKER_CSV).exists():
        with open(TRACKER_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        log.info(f"Created new tracker: {TRACKER_CSV}")
        return {}
    tracker = {}
    with open(TRACKER_CSV, "r", newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("email"):
                tracker[row["email"].lower()] = row
    log.info(f"Loaded {len(tracker)} records from tracker")
    return tracker


def save_tracker(tracker: dict):
    with open(TRACKER_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in tracker.values():
            writer.writerow(row)


def upsert(tracker: dict, prospect: dict, status: str):
    email = prospect["email"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    if email not in tracker:
        tracker[email] = {
            "email":             email,
            "first_name":        prospect.get("first_name", ""),
            "last_name":         prospect.get("last_name", ""),
            "company":           prospect.get("company", ""),
            "title":             prospect.get("title", ""),
            "status":            status,
            "initial_sent_date": now if status == "initial_sent"   else "",
            "followup1_date":    now if status == "followup1_sent" else "",
            "followup2_date":    now if status == "followup2_sent" else "",
            "replied":           "No",
            "unsubscribed":      "No",
            "last_updated":      now,
        }
    else:
        tracker[email]["status"]       = status
        tracker[email]["last_updated"] = now
        if status == "initial_sent":
            tracker[email]["initial_sent_date"] = now
        elif status == "followup1_sent":
            tracker[email]["followup1_date"] = now
        elif status == "followup2_sent":
            tracker[email]["followup2_date"] = now


def mark_replied(tracker, email):
    if email in tracker:
        tracker[email]["replied"]      = "Yes"
        tracker[email]["status"]       = "replied"
        tracker[email]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def days_since(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:16], "%Y-%m-%d %H:%M")
        return (datetime.now() - dt).days
    except ValueError:
        return None

def is_unsubscribed(r): return str(r.get("unsubscribed","")).lower() in ("yes","1","true")
def has_replied(r):     return str(r.get("replied","")).lower()       in ("yes","1","true")

# ─── GMAIL ───────────────────────────────────────────────────────────────────

def get_gmail_service():
    creds = None
    if os.path.exists(GMAIL_TOKEN_FILE):
        with open(GMAIL_TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GMAIL_CREDENTIALS, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GMAIL_TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


def send_email(service, to: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEMultipart()
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me", body={"raw": raw}).execute()
        log.info(f"  ✓ Sent → {to}")
        return True
    except Exception as e:
        log.error(f"  ✗ Failed → {to}: {e}")
        return False


def check_for_reply(service, prospect_email: str) -> bool:
    try:
        result = service.users().messages().list(
            userId="me", q=f"from:{prospect_email}").execute()
        return len(result.get("messages", [])) > 0
    except Exception as e:
        log.warning(f"Reply check failed for {prospect_email}: {e}")
        return False

# ─── MAIN ────────────────────────────────────────────────────────────────────

def run_outreach():
    log.info("=" * 60)
    log.info("Aggarwal Electric — Outreach run started")
    log.info("=" * 60)

    gmail      = get_gmail_service()
    tracker    = load_tracker()
    prospects  = load_prospects()
    sent_today = 0

    # ── Phase 1: Follow-ups on existing contacts ──────────────────────────
    log.info("── Phase 1: Follow-ups ──")
    for email, record in list(tracker.items()):
        if sent_today >= EMAILS_PER_DAY:
            log.warning("Daily limit reached.")
            break

        if is_unsubscribed(record) or has_replied(record):
            continue

        status     = record.get("status", "")
        first_name = record.get("first_name", "")
        prospect   = {
            "email":      email,
            "first_name": first_name,
            "last_name":  record.get("last_name", ""),
            "company":    record.get("company", ""),
            "title":      record.get("title", ""),
        }

        # Check for reply in inbox
        if check_for_reply(gmail, email):
            log.info(f"Reply detected from {email} — marking replied")
            mark_replied(tracker, email)
            continue

        # Follow-up 1 — Day 5
        if status == "initial_sent":
            days = days_since(record.get("initial_sent_date", ""))
            if days is not None and days >= FOLLOW_UP_1_DAYS:
                log.info(f"Follow-up 1 → {email} ({days}d)")
                if send_email(gmail, email, SUBJECT,
                              get_followup1_body(first_name, email)):
                    upsert(tracker, prospect, "followup1_sent")
                    sent_today += 1
                    time.sleep(DELAY_BETWEEN_EMAILS)

        # Follow-up 2 — Day 10
        elif status == "followup1_sent":
            days = days_since(record.get("followup1_date", ""))
            if days is not None and days >= (FOLLOW_UP_2_DAYS - FOLLOW_UP_1_DAYS):
                log.info(f"Follow-up 2 → {email} ({days}d)")
                if send_email(gmail, email, SUBJECT,
                              get_followup2_body(first_name, email)):
                    upsert(tracker, prospect, "followup2_sent")
                    sent_today += 1
                    time.sleep(DELAY_BETWEEN_EMAILS)

    # ── Phase 2: New prospects from prospects.csv ─────────────────────────
    log.info("── Phase 2: New prospects from CSV ──")
    for prospect in prospects:
        if sent_today >= EMAILS_PER_DAY:
            log.warning("Daily limit reached.")
            break

        email = prospect["email"]

        # Skip if already in tracker with a status
        if email in tracker and tracker[email].get("status"):
            log.info(f"  Skip (already contacted): {email}")
            continue

        # Skip unsubscribed
        if email in tracker and is_unsubscribed(tracker[email]):
            continue

        log.info(f"Initial → {email} ({prospect.get('company','')})")
        if send_email(gmail, email, SUBJECT,
                      get_initial_body(prospect["first_name"], email)):
            upsert(tracker, prospect, "initial_sent")
            sent_today += 1
            time.sleep(DELAY_BETWEEN_EMAILS)

    # ── Save tracker ──────────────────────────────────────────────────────
    save_tracker(tracker)
    log.info(f"Tracker saved → {TRACKER_CSV}")
    log.info(f"── Done. Sent: {sent_today}/{EMAILS_PER_DAY} ──")


if __name__ == "__main__":
    run_outreach()
