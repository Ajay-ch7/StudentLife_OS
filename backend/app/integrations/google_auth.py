import json
import logging
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from app.core.config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)

# Scopes for Google Calendar and Gmail (manage calendar, read emails, manage drafts, send emails)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


class GoogleAuthError(Exception):
    """Raised when Google OAuth authentication fails or credentials are missing."""
    pass


def get_credentials_path() -> Path:
    settings = get_settings()
    path = Path(settings.google_client_secrets_file)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def get_token_path() -> Path:
    settings = get_settings()
    path = Path(settings.google_token_file)
    if not path.is_absolute():
        path = BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_google_authenticated() -> bool:
    """Check whether valid Google credentials are saved locally."""
    token_path = get_token_path()
    if not token_path.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)
        return bool(creds and (creds.valid or creds.refresh_token))
    except Exception:
        return False


def get_google_credentials(interactive: bool = False) -> Credentials | None:
    """
    Retrieve valid Google OAuth2 credentials.
    If credentials exist but are expired, automatically refreshes them.
    If no credentials exist and interactive=True, launches local browser OAuth flow.
    """
    token_path = get_token_path()
    secrets_path = get_credentials_path()
    creds: Credentials | None = None

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), GOOGLE_SCOPES)
        except Exception as e:
            logger.warning("Failed to load existing Google token file: %s", e)
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("Refreshing expired Google OAuth access token...")
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:
            logger.error("Failed to refresh Google token: %s", e)
            creds = None

    if creds and creds.valid:
        return creds

    # If not interactive and credentials are missing, return None
    if not interactive:
        return None

    # Interactive flow to login via browser
    if not secrets_path.exists():
        raise GoogleAuthError(
            f"Google client secrets file not found at '{secrets_path}'. "
            "Please download your OAuth 2.0 Client ID JSON from Google Cloud Console "
            "and save it as 'credentials.json' in the project root."
        )

    logger.info("Launching Google OAuth consent flow in local browser...")
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline", timeout_seconds=180)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Google OAuth login successful. Token saved to %s", token_path)
    return creds


def get_calendar_service() -> Resource | None:
    """Build and return an authorized Google Calendar API service client."""
    creds = get_google_credentials(interactive=False)
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def get_gmail_service() -> Resource | None:
    """Build and return an authorized Gmail API service client."""
    creds = get_google_credentials(interactive=False)
    if not creds or not creds.valid:
        return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


if __name__ == "__main__":
    import sys
    print("==================================================")
    print(" StudentLife OS - Google OAuth Setup")
    print("==================================================")
    secrets = get_credentials_path()
    if not secrets.exists():
        print(f"\n[ERROR] File not found: {secrets}")
        print("Please place your OAuth Client ID JSON from Google Cloud Console at that path.")
        sys.exit(1)

    print(f"\nUsing client secrets from: {secrets}")
    print("Opening browser for OAuth sign-in with Google Calendar & Gmail scopes...")
    try:
        credentials = get_google_credentials(interactive=True)
        print("\n[SUCCESS] Google Authentication completed!")
        print(f"Token saved to: {get_token_path()}")
    except Exception as exc:
        print(f"\n[ERROR] Authentication failed: {exc}")
        sys.exit(1)
