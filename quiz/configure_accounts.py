"""Build ignored Streamlit secrets from downloaded Google credential files.

Never print credentials. Existing secrets files are not overwritten.
"""

import argparse
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    """Configuration guidance that contains no private input values."""


def configuration(oauth, service_account, app_url):
    url = urlsplit(app_url)
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    if (url.scheme != "https" and not (url.scheme == "http" and local)) or not url.hostname \
            or url.query or url.fragment or url.username or url.password:
        raise ConfigurationError("Use the app's HTTPS URL, or http://localhost:8501 for local testing.")
    if not isinstance(oauth, dict) or not isinstance(service_account, dict):
        raise ConfigurationError("Choose downloaded OAuth and service-account JSON files.")
    web = oauth.get("web", {})
    if not isinstance(web, dict) or not all(
            isinstance(web.get(key), str) and web[key] for key in ("client_id", "client_secret")):
        raise ConfigurationError("Download OAuth credentials for a Web application, not a Desktop application.")
    required = ("project_id", "client_email", "private_key", "token_uri")
    if service_account.get("type") != "service_account" or not all(
            isinstance(service_account.get(key), str) and service_account[key] for key in required):
        raise ConfigurationError("Choose the downloaded Google service-account JSON key.")
    callback = app_url.rstrip("/") + "/oauth2callback"
    if callback not in web.get("redirect_uris", []):
        raise ConfigurationError(f"Register {callback} as an authorized redirect URI, then download the OAuth JSON again.")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ["# Private account credentials. Do not commit or paste into chat.", "[auth]",
             f"redirect_uri = {quote(callback)}", f"cookie_secret = {quote(secrets.token_urlsafe(48))}", "",
             "[auth.google]", f"client_id = {quote(web['client_id'])}",
             f"client_secret = {quote(web['client_secret'])}",
             'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"', "",
             "[firestore]", f"project_id = {quote(service_account['project_id'])}",
             'database_id = "(default)"', "", "[firestore.service_account]"]
    for key, value in service_account.items():
        if isinstance(value, str):
            lines.append(f"{quote(key)} = {quote(value)}")
    return "\n".join(lines) + "\n"


def write_configuration(oauth_path, service_account_path, app_url, output):
    oauth = json.loads(Path(oauth_path).read_text(encoding="utf-8-sig"))
    service_account = json.loads(Path(service_account_path).read_text(encoding="utf-8-sig"))
    text = configuration(oauth, service_account, app_url)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as destination:
        destination.write(text)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oauth", type=Path, required=True)
    parser.add_argument("--service-account", type=Path, required=True)
    parser.add_argument("--app-url", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".streamlit" / "secrets.toml")
    args = parser.parse_args()
    try:
        output = write_configuration(args.oauth, args.service_account, args.app_url, args.output)
    except FileExistsError:
        parser.exit(1, "A secrets file already exists. It was not overwritten.\n")
    except ConfigurationError as exc:
        parser.exit(1, f"{exc}\n")
    except (ValueError, OSError):
        # JSON parsing/read errors can include parts of a private input file.
        parser.exit(1, "Could not create configuration. Check the credential files, app URL and registered callback.\n")
    print(f"Private configuration saved to {output}. No credentials were printed.")
    print("For Community Cloud, copy this file into the app's Settings > Secrets editor, then reboot the app.")


if __name__ == "__main__":
    main()
