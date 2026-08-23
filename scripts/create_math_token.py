#!/usr/bin/env python3
import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Full YouTube account scope is required because the publisher uploads videos and
# automatically adds every Long and Short to the Daily Math playlist.
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
]

DEFAULT_PLAYLIST_ID = "PLdWKMS0QH1hc"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the one-time OAuth token used by the Daily Math GitHub publisher."
    )
    parser.add_argument("client_secret_json", help="Google OAuth Desktop App client_secret JSON")
    parser.add_argument("--output", default="token_math.json")
    args = parser.parse_args()

    client_secret = Path(args.client_secret_json).expanduser().resolve()
    if not client_secret.is_file():
        raise SystemExit(f"Client secret file not found: {client_secret}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    response = youtube.channels().list(part="id,snippet", mine=True, maxResults=50).execute()
    items = response.get("items", [])
    if len(items) != 1:
        raise SystemExit(f"Expected exactly one authenticated YouTube channel; got {len(items)}")

    channel = items[0]
    channel_id = channel["id"]
    title = channel.get("snippet", {}).get("title", "")

    output = Path(args.output).expanduser().resolve()
    output.write_text(creds.to_json(), encoding="utf-8")

    print(f"Authenticated channel: {title} ({channel_id})")
    print(f"Default playlist: {DEFAULT_PLAYLIST_ID}")
    print(f"Saved authorized-user JSON: {output}")
    print()
    print("GitHub Actions secrets to configure:")
    print(f"EXPECTED_MATH_CHANNEL_ID={channel_id}")
    print(f"YOUTUBE_MATH_TOKEN_JSON=<paste the complete contents of {output.name}>")
    print()
    print("Do not commit the token file or client_secret JSON to GitHub.")


if __name__ == "__main__":
    main()
