"""
Run this ONCE on your local machine to generate gmail_token.pickle.
After running, encode it to base64 and store as a GitHub Secret.

Usage:
    python generate_gmail_token.py
"""

import pickle
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import os

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

def main():
    creds = None
    if os.path.exists("gmail_token.pickle"):
        with open("gmail_token.pickle", "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("gmail_credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("gmail_token.pickle", "wb") as f:
            pickle.dump(creds, f)

    # Encode to base64 for GitHub secret
    with open("gmail_token.pickle", "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    with open("gmail_token_b64.txt", "w") as f:
        f.write(encoded)

    print("✓ gmail_token.pickle created")
    print("✓ gmail_token_b64.txt created — copy its contents into GitHub Secret: GMAIL_TOKEN_PICKLE_B64")

if __name__ == "__main__":
    main()
