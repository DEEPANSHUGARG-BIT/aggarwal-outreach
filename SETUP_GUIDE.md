# AL/AR Cable — Automated Vendor Outreach System
## Complete Setup Guide

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  GitHub Actions (Daily 9 AM IST)            │
└─────────────────────┬───────────────────────────────────────┘
                      │  triggers
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                     outreach.py                             │
│                                                             │
│  Phase 1: Follow-ups          Phase 2: New Prospects        │
│  ─────────────────────        ─────────────────────────     │
│  Read tracker sheet     ───▶  Fetch from Apollo.io          │
│  Check reply status           Filter by title/industry      │
│  Send FU1 after 5 days        Skip known emails             │
│  Send FU2 after 10 days       Send initial email            │
│  Mark replied/unsub           Log to Google Sheets          │
└──────────┬────────────────────────────┬────────────────────┘
           │                            │
           ▼                            ▼
    ┌─────────────┐            ┌─────────────────┐
    │  Gmail API  │            │  Google Sheets  │
    │  (Send)     │            │  (Tracker)      │
    └─────────────┘            └─────────────────┘
           │                            │
           ▼                            ▼
    ┌─────────────┐            ┌─────────────────┐
    │  Gmail API  │            │  Apollo.io API  │
    │  (Read/     │            │  (Prospect      │
    │   replies)  │            │   search)       │
    └─────────────┘            └─────────────────┘
```

### Email Flow per Prospect
```
Day 0  →  Initial email sent
Day 5  →  Follow-up 1 (if no reply)
Day 10 →  Follow-up 2 (if no reply)
         Reply detected at any point → stop sequence
         Unsubscribe reply → stop + mark
```

### Google Sheet Columns
| Email | First Name | Last Name | Company | Title | LinkedIn |
| Apollo ID | Status | Initial Sent Date | Follow-up 1 Date |
| Follow-up 2 Date | Replied | Unsubscribed | Last Updated | Notes |

---

## Step 1 — Apollo.io API Key

1. Log in to [apollo.io](https://apollo.io)
2. Go to **Settings → Integrations → API**
3. Click **Create API Key** → copy it
4. You'll use this as `APOLLO_API_KEY`

**Apollo Search Filters used in the script:**
- Titles: Purchase Manager, Procurement Manager, Sourcing Manager, Supply Chain Manager
- Keywords: solar EPC, solar developer, renewable energy, EPC contractor
- Location: India
- Email status: verified / likely to engage

---

## Step 2 — Gmail API Setup

### 2a. Enable Gmail API
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (e.g. "Cable Outreach")
3. Go to **APIs & Services → Enable APIs**
4. Search **Gmail API** → Enable it

### 2b. Create OAuth Credentials
1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth Client ID**
3. Application type: **Desktop App**
4. Name it: `cable-outreach-gmail`
5. Download the JSON → rename to `gmail_credentials.json`
6. Place it in your project folder

### 2c. Configure OAuth Consent Screen
1. Go to **OAuth Consent Screen**
2. User type: **External**
3. App name: `Cable Outreach`
4. Add your Gmail as a test user
5. Scopes needed:
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/gmail.readonly`

### 2d. Generate the Token (run once on your laptop)
```bash
pip install -r requirements.txt
python generate_gmail_token.py
```
This opens a browser → log in with your Gmail → authorizes the app.
It creates `gmail_token.pickle` and `gmail_token_b64.txt`.

---

## Step 3 — Google Sheets API Setup

### 3a. Create a Service Account
1. In Google Cloud Console → **IAM & Admin → Service Accounts**
2. Click **Create Service Account**
3. Name: `cable-outreach-sheets`
4. Role: **Editor**
5. Click **Create Key → JSON** → download it
6. Rename to `sheets_credentials.json`

### 3b. Enable Sheets + Drive APIs
1. **APIs & Services → Enable APIs**
2. Enable **Google Sheets API**
3. Enable **Google Drive API**

### 3c. Share the Sheet
The script auto-creates the Google Sheet on first run.
After first run, the sheet appears in the service account's Drive.
To view it yourself: open `sheets_credentials.json`, copy the `client_email` value,
then share the sheet with that email address in Google Sheets.

---

## Step 4 — GitHub Secrets Setup

In your GitHub repo → **Settings → Secrets and Variables → Actions → New secret**

Add these 6 secrets:

| Secret Name | Value |
|---|---|
| `APOLLO_API_KEY` | Your Apollo API key |
| `SENDER_EMAIL` | your@gmail.com |
| `SENDER_NAME` | Your Full Name |
| `GMAIL_CREDENTIALS_JSON` | Full contents of `gmail_credentials.json` |
| `SHEETS_CREDENTIALS_JSON` | Full contents of `sheets_credentials.json` |
| `GMAIL_TOKEN_PICKLE_B64` | Contents of `gmail_token_b64.txt` |

To get the JSON file contents:
```bash
cat gmail_credentials.json   # copy everything
cat sheets_credentials.json  # copy everything
cat gmail_token_b64.txt      # copy everything
```

---

## Step 5 — Add Your Email Template

Open `outreach.py` and find the three template functions:
- `get_initial_email()` — Day 0
- `get_followup1_email()` — Day 5
- `get_followup2_email()` — Day 10

Replace the body text with your actual email template.
The variables available are: `{first_name}`, `{company}`, `{title}`

---

## Step 6 — Push to GitHub

```bash
# Create a new GitHub repo called "cable-outreach"
# Then in your project folder:

git init
git add outreach.py requirements.txt generate_gmail_token.py
git add .github/
git commit -m "Initial outreach system"
git remote add origin https://github.com/YOURNAME/cable-outreach.git
git push -u origin main
```

**Do NOT commit credential files.**
The `.gitignore` below protects them.

---

## Step 7 — Verify the Schedule

The GitHub Action runs every day at **9:00 AM IST** automatically.

To test it manually:
1. Go to your GitHub repo → **Actions** tab
2. Click **Daily Cable Outreach** → **Run workflow** → **Run workflow**
3. Watch the logs in real time

---

## Files to Keep Secret (never commit)
```
gmail_credentials.json
gmail_token.pickle
gmail_token_b64.txt
sheets_credentials.json
outreach.log
```

---

## Anti-Spam Compliance Checklist
- ✅ Every email includes unsubscribe instructions ("Reply with Unsubscribe")
- ✅ Sender name and identity is clear
- ✅ No misleading subject lines
- ✅ Relevant targeting (B2B procurement contacts in your industry)
- ✅ Rate limited to 80 emails/day (well below Gmail's 500/day)
- ✅ Duplicate prevention via Google Sheets tracker
- ✅ Unsubscribe requests are logged and honoured
- ✅ Follows CAN-SPAM / India IT Act email guidelines

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Token expired` error | Re-run `generate_gmail_token.py` locally and update GitHub secret |
| `Apollo 401` error | Check `APOLLO_API_KEY` secret is correct |
| Sheet not found | Run once locally first to create it, then share with your email |
| Emails going to spam | Warm up your Gmail first, send <20/day initially |
| `quota exceeded` Gmail error | Reduce `EMAILS_PER_DAY` in outreach.py |
