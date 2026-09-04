"""
Standalone Google OAuth setup script for StudentLife OS.
Run this directly to authenticate your Google Account for Google Calendar & Gmail API:
    python connect_google.py
"""
import os
import sys
from pathlib import Path

# Add backend and project root to Python search path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "backend"))
sys.path.insert(0, str(ROOT_DIR))

from app.integrations.google_auth import (
    get_credentials_path,
    get_google_credentials,
    get_token_path,
    is_google_authenticated,
)

def main() -> None:
    print("==================================================")
    print(" StudentLife OS - Google Account Connection")
    print(" (Google Calendar & Gmail API OAuth2)")
    print("==================================================")

    secrets = get_credentials_path()
    if not secrets.exists():
        print(f"\n[ERROR] Missing credentials file at: {secrets}")
        print("Please ensure your Google Cloud OAuth Client ID JSON is saved as 'credentials.json' in this folder.")
        sys.exit(1)

    print(f"\n[OK] Found client secrets: {secrets.name}")

    if is_google_authenticated():
        print(f"[OK] You are already authenticated! Token file: {get_token_path()}")
        reauth = input("Do you want to re-authenticate with a new account? (y/N): ").strip().lower()
        if reauth != "y":
            print("\nSetup complete! Google Calendar and Gmail are connected.")
            return

    print("\nOpening your default browser for Google Sign-In...")
    print("Please select your Google Account and click 'Continue / Allow' on the permissions screen.")
    print("(If Google shows an 'unverified app' screen, click 'Advanced' -> 'Go to StudentLife OS (unsafe)' to proceed.)\n")

    try:
        creds = get_google_credentials(interactive=True)
        if creds and creds.valid:
            print("\n==================================================")
            print(" [SUCCESS] Google Authentication Complete!")
            print(f" Token successfully saved to: {get_token_path()}")
            print(" Google Calendar & Gmail are now connected to OpenClaw.")
            print("==================================================")
        else:
            print("\n[WARNING] Flow finished but credentials could not be verified.")
    except Exception as exc:
        print(f"\n[ERROR] Authentication failed: {exc}")
        sys.exit(1)

if __name__ == "__main__":
    main()
