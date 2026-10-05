"""OAuth 2.0 login and cached credentials for the Google Health API."""

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


def login(client_secret: Path, token_path: Path, scopes: list[str], port: int = 0) -> Credentials:
    """Run the browser-based installed-app flow and cache the resulting token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), scopes=scopes)
    # access_type=offline + prompt=consent ensures we get a refresh token.
    creds = flow.run_local_server(
        port=port, access_type="offline", prompt="consent", open_browser=True
    )
    save(creds, token_path)
    return creds


MANUAL_REDIRECT_URI = "http://localhost:8080/"


def start_manual_login(client_secret: Path, pending_path: Path, scopes: list[str]) -> str:
    """Begin a login on a machine without a browser; return the URL to open.

    After consent the browser is sent to localhost, which won't load; the user
    copies that URL back into `finish_manual_login`.
    """
    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_secrets_file(
        str(client_secret), scopes=scopes, redirect_uri=MANUAL_REDIRECT_URI
    )
    url, state = flow.authorization_url(access_type="offline", prompt="consent")
    pending_path.write_text(
        json.dumps({"state": state, "code_verifier": flow.code_verifier, "scopes": scopes})
    )
    pending_path.chmod(0o600)
    return url


def finish_manual_login(
    client_secret: Path, pending_path: Path, token_path: Path, redirect_url: str
) -> Credentials:
    """Exchange the code in the pasted localhost redirect URL for a token."""
    from google_auth_oauthlib.flow import Flow

    if not pending_path.exists():
        raise FileNotFoundError("No login in progress. Run `fitbit-pull login --manual` first.")
    pending = json.loads(pending_path.read_text())
    flow = Flow.from_client_secrets_file(
        str(client_secret),
        scopes=pending["scopes"],
        redirect_uri=MANUAL_REDIRECT_URI,
        state=pending["state"],
        code_verifier=pending["code_verifier"],
    )
    # The redirect target is plain-http localhost; Google allows it for desktop clients.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    # Google may grant scopes in a different order or as a subset.
    os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
    flow.fetch_token(authorization_response=redirect_url.strip())
    save(flow.credentials, token_path)
    pending_path.unlink()
    return flow.credentials


def load(token_path: Path) -> Credentials:
    """Load cached credentials, refreshing the access token if it has expired."""
    if not token_path.exists():
        raise FileNotFoundError(
            f"No token at {token_path}. Run `fitbit-pull login` first."
        )
    creds = Credentials.from_authorized_user_file(str(token_path))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        save(creds, token_path)
    return creds


def save(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    token_path.chmod(0o600)
