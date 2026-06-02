"""
Aggarwal Electric Company — Automated Vendor Empanelment Outreach
=================================================================
Sends your fixed email template + catalogue PDF via Gmail.
Fetches prospects from Apollo.io.
Tracks everything in a LOCAL CSV file (no Google Sheets needed).
Handles follow-ups at Day 5 and Day 10 if no reply.
"""

import os
import csv
import time
import base64
import logging
import requests
import pickle
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ─── CONFIG ──────────────────────────────────────────────────────────────────

APOLLO_API_KEY       = os.environ.get("APOLLO_API_KEY", "YOUR_APOLLO_API_KEY")
SENDER_EMAIL         = os.environ.get("SENDER_EMAIL", "aggelectric@gmail.com")
SENDER_NAME          = os.environ.get("SENDER_NAME", "Deepanshu Garg")
CATALOGUE_PATH       = "AGGARWAL_ELECTRIC_CATALOGUE.pdf"
GMAIL_CREDENTIALS    = "gmail_credentials.json"
GMAIL_TOKEN_FILE     = "gmail_token.pickle"
TRACKER_CSV          = "outreach_tracker.csv"   # auto-created on first run

# Rate limits
EMAILS_PER_DAY       = 15
DELAY_BETWEEN_EMAILS = 60    # seconds between each send
FOLLOW_UP_1_DAYS     = 5
FOLLOW_UP_2_DAYS     = 10

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Apollo search filters
APOLLO_TITLES = [
    "Purchase Manager", "Purchasing Manager",
    "Procurement Manager", "Procurement Head",
    "Sourcing Manager", "Sourcing Head",
    "Supply Chain Manager", "Supply Chain Head",
    "Materials Manager", "Materials Head",
]
APOLLO_KEYWORDS = [
    "solar EPC", "solar developer", "solar energy",
    "renewable energy", "EPC contractor", "solar power",
    "infrastructure", "industrial", "manufacturing",
]

# ─── CSV COLUMNS ─────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "email", "first_name", "last_name", "company", "title",
    "status", "initial_sent_date", "followup1_date", "followup2_date",
    "replied", "unsubscribed", "last_updated", "notes"
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

Please find our company profile and product catalogue attached for your reference.

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

We would be glad to be registered as an approved vendor with your organization. Please let us know the process or documentation required and we will promptly comply.

I have re-attached our catalogue for your convenience.

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

Our catalogue is attached for future reference. No action is needed from your end right now.

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

# ─── CSV TRACKER ─────────────────────────────────────────────────────────────

def load_tracker() -> dict:
    """Load CSV into dict keyed by email. Creates file if missing."""
    if not Path(TRACKER_CSV).exists():
        with open(TRACKER_CSV, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
        log.info(f"Created new tracker: {TRACKER_CSV}")
        return {}

    tracker = {}
    with open(TRACKER_CSV, "r", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("email"):
                tracker[row["email"].lower()] = row
    log.info(f"Loaded {len(tracker)} records from tracker")
    return tracker


def save_tracker(tracker: dict):
    """Write entire tracker dict back to CSV."""
    with open(TRACKER_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in tracker.values():
            writer.writerow(row)


def upsert(tracker: dict, prospect: dict, status: str):
    """Add new prospect or update existing one in tracker dict."""
    email = prospect["email"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")

    if email not in tracker:
        tracker[email] = {
            "email":              email,
            "first_name":         prospect.get("first_name", ""),
            "last_name":          prospect.get("last_name", ""),
            "company":            prospect.get("company", ""),
            "title":              prospect.get("title", ""),
            "status":             status,
            "initial_sent_date":  now if status == "initial_sent"   else "",
            "followup1_date":     now if status == "followup1_sent" else "",
            "followup2_date":     now if status == "followup2_sent" else "",
            "replied":            "No",
            "unsubscribed":       "No",
            "last_updated":       now,
            "notes":              "",
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


def mark_replied(tracker: dict, email: str):
    if email in tracker:
        tracker[email]["replied"]      = "Yes"
        tracker[email]["status"]       = "replied"
        tracker[email]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def mark_unsubscribed(tracker: dict, email: str):
    if email in tracker:
        tracker[email]["unsubscribed"] = "Yes"
        tracker[email]["status"]       = "unsubscribed"
        tracker[email]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def days_since(date_str: str):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str[:16], "%Y-%m-%d %H:%M")
        return (datetime.now() - dt).days
    except ValueError:
        return None

def is_unsubscribed(r): return str(r.get("unsubscribed","")).lower() in ("yes","1","true")
def has_replied(r):     return str(r.get("replied","")).lower()       in ("yes","1","true")

# ─── CATALOGUE ATTACHMENT ────────────────────────────────────────────────────

def attach_catalogue(msg: MIMEMultipart) -> MIMEMultipart:
    if not os.path.exists(CATALOGUE_PATH):
        log.warning(f"Catalogue not found at '{CATALOGUE_PATH}' — sending without it.")
        return msg
    with open(CATALOGUE_PATH, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition",
                    'attachment; filename="Aggarwal_Electric_Company_Catalogue.pdf"')
    msg.attach(part)
    return msg

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
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS, GMAIL_SCOPES)
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
        msg = attach_catalogue(msg)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
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

# ─── APOLLO ──────────────────────────────────────────────────────────────────

def fetch_apollo_prospects(page=1, per_page=25) -> list:
    url     = "https://api.apollo.io/v1/mixed_people/search"
    headers = {"Content-Type": "application/json",
               "Cache-Control": "no-cache",
               "X-Api-Key": APOLLO_API_KEY}
    payload = {
        "page": page, "per_page": per_page,
        "person_titles": APOLLO_TITLES,
        "q_organization_keyword_tags": APOLLO_KEYWORDS,
        "person_locations": ["India"],
        "contact_email_status": ["verified", "likely to engage"],
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        people = resp.json().get("people", [])
        log.info(f"Apollo: {len(people)} prospects (page {page})")
        return people
    except requests.RequestException as e:
        log.error(f"Apollo error: {e}")
        return []


def parse_prospect(person: dict):
    email = person.get("email")
    if not email or "@" not in email:
        return None
    return {
        "email":      email.lower().strip(),
        "first_name": (person.get("first_name") or "").strip(),
        "last_name":  (person.get("last_name")  or "").strip(),
        "company":    ((person.get("organization") or {}).get("name") or "").strip(),
        "title":      (person.get("title") or "").strip(),
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────

def run_outreach():
    log.info("=" * 60)
    log.info("Aggarwal Electric — Outreach run started")
    log.info("=" * 60)

    gmail      = get_gmail_service()
    tracker    = load_tracker()
    sent_today = 0

    # ── Phase 1: Follow-ups ───────────────────────────────────────────────
    log.info("── Phase 1: Follow-ups ──")
    for email, record in list(tracker.items()):
        if sent_today >= EMAILS_PER_DAY:
            log.warning("Daily limit reached.")
            break

        if is_unsubscribed(record) or has_replied(record):
            continue

        status     = record.get("status", "")
        first_name = record.get("first_name", "")
        prospect   = {"email": email, "first_name": first_name,
                      "last_name": record.get("last_name",""),
                      "company": record.get("company",""),
                      "title": record.get("title","")}

        # Check for reply
        if check_for_reply(gmail, email):
            log.info(f"Reply detected from {email}")
            mark_replied(tracker, email)
            continue

        # Follow-up 1 — after 5 days
        if status == "initial_sent":
            days = days_since(record.get("initial_sent_date", ""))
            if days is not None and days >= FOLLOW_UP_1_DAYS:
                log.info(f"Follow-up 1 → {email} ({days}d since initial)")
                if send_email(gmail, email, SUBJECT, get_followup1_body(first_name, email)):
                    upsert(tracker, prospect, "followup1_sent")
                    sent_today += 1
                    time.sleep(DELAY_BETWEEN_EMAILS)

        # Follow-up 2 — after 10 days
        elif status == "followup1_sent":
            days = days_since(record.get("followup1_date", ""))
            if days is not None and days >= (FOLLOW_UP_2_DAYS - FOLLOW_UP_1_DAYS):
                log.info(f"Follow-up 2 → {email} ({days}d since FU1)")
                if send_email(gmail, email, SUBJECT, get_followup2_body(first_name, email)):
                    upsert(tracker, prospect, "followup2_sent")
                    sent_today += 1
                    time.sleep(DELAY_BETWEEN_EMAILS)

    # ── Phase 2: New prospects from Apollo ───────────────────────────────
    log.info("── Phase 2: New prospects ──")
    page = 1
    while sent_today < EMAILS_PER_DAY:
        people = fetch_apollo_prospects(page=page, per_page=25)
        if not people:
            break

        for person in people:
            if sent_today >= EMAILS_PER_DAY:
                break
            prospect = parse_prospect(person)
            if not prospect:
                continue
            email = prospect["email"]

            # Skip already contacted
            if email in tracker and tracker[email].get("status"):
                log.info(f"  Skip (known): {email}")
                continue

            log.info(f"Initial → {email} ({prospect['company']})")
            if send_email(gmail, email, SUBJECT,
                          get_initial_body(prospect["first_name"], email)):
                upsert(tracker, prospect, "initial_sent")
                sent_today += 1
                time.sleep(DELAY_BETWEEN_EMAILS)

        page += 1
        time.sleep(2)

    # ── Save tracker CSV ─────────────────────────────────────────────────
    save_tracker(tracker)
    log.info(f"Tracker saved → {TRACKER_CSV}")
    log.info(f"── Done. Sent: {sent_today}/{EMAILS_PER_DAY} ──")


if __name__ == "__main__":
    run_outreach()
