#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import publish_package as base

SCHEDULE_TIMEZONE = "America/Toronto"
PAIR_PUBLISH_TIME = time(10, 0)
START_DATE_RE = re.compile(r"(?im)^\s*START_DATE\s*=\s*(\d{4}-\d{2}-\d{2})\s*$")
YOUTUBE_ACCOUNT_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_FORCE_SSL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
YOUTUBE_PARTNER_SCOPE = "https://www.googleapis.com/auth/youtubepartner"
DEFAULT_PLAYLIST_ID = "PLdWKMS0QH1hc"

# The scheduled publisher now needs playlist write access in addition to video upload access.
# A single full YouTube account scope covers videos.insert, channels.list, thumbnails.set,
# playlistItems.list, and playlistItems.insert.
base.SCOPES = [YOUTUBE_ACCOUNT_SCOPE]


def fail(message: str) -> None:
    raise RuntimeError(message)


def read_start_date(release_body_path: Path) -> date:
    if not release_body_path.is_file():
        fail(f"Release body file not found: {release_body_path}")
    body = release_body_path.read_text(encoding="utf-8")
    matches = START_DATE_RE.findall(body)
    if len(matches) != 1:
        fail(
            "Release description must contain exactly one line in this format: "
            "START_DATE=YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(matches[0])
    except ValueError as exc:
        fail(f"Invalid START_DATE: {matches[0]} ({exc})")


def add_schedule(manifest: list[dict], start_date: date) -> list[dict]:
    if not manifest:
        fail("Manifest is empty")

    tz = ZoneInfo(SCHEDULE_TIMEZONE)
    first_number = min(int(item["number"]) for item in manifest)
    now_utc = datetime.now(timezone.utc)

    for item in manifest:
        day_offset = int(item["number"]) - first_number
        local_day = start_date + timedelta(days=day_offset)
        local_dt = datetime.combine(local_day, PAIR_PUBLISH_TIME, tzinfo=tz)
        utc_dt = local_dt.astimezone(timezone.utc)

        item["scheduled_local"] = local_dt.isoformat()
        item["publish_at"] = utc_dt.isoformat().replace("+00:00", "Z")

    first_publish = min(datetime.fromisoformat(item["publish_at"].replace("Z", "+00:00")) for item in manifest)
    if first_publish <= now_utc:
        fail(
            "The first scheduled publish time is not in the future. "
            f"START_DATE={start_date.isoformat()} maps to "
            f"{PAIR_PUBLISH_TIME.strftime('%H:%M')} {SCHEDULE_TIMEZONE}."
        )

    return manifest


def upload_scheduled_item(youtube, channel_id: str, item: dict) -> dict:
    body = {
        "snippet": {
            "title": item["title"],
            "description": item["description"],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": item["publish_at"],
            "selfDeclaredMadeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(
            item["path"],
            mimetype="video/mp4",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        ),
        notifySubscribers=False,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status is not None:
            print(
                f"Upload progress {item['number']} {item['type']}: "
                f"{int(status.progress() * 100)}%"
            )

    video_id = response.get("id")
    if not video_id:
        fail(f"YouTube did not return a video_id for {item['number']} {item['type']}")

    thumbnail_requested = bool(item.get("thumbnail"))
    thumbnail_ok = None
    thumbnail_error = None
    if thumbnail_requested:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(item["thumbnail"], resumable=False),
            ).execute()
            thumbnail_ok = True
        except HttpError as exc:
            thumbnail_ok = False
            thumbnail_error = base.http_error_detail(exc)

    return {
        "ok": True,
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy": "private",
        "youtube_status": "scheduled",
        "channel": "math",
        "channel_id": channel_id,
        "publish_at": item["publish_at"],
        "scheduled_local": item["scheduled_local"],
        "thumbnail_requested": thumbnail_requested,
        "thumbnail_ok": thumbnail_ok,
        "thumbnail_error": thumbnail_error,
    }


def require_playlist_oauth_scope() -> None:
    raw = os.getenv(base.TOKEN_JSON_ENV, "").strip()
    if not raw:
        fail(f"Required GitHub Actions secret {base.TOKEN_JSON_ENV} is not configured")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{base.TOKEN_JSON_ENV} is not valid authorized-user JSON: {exc}")

    scopes = info.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    granted = set(scopes)
    playlist_write_scopes = {
        YOUTUBE_ACCOUNT_SCOPE,
        YOUTUBE_FORCE_SSL_SCOPE,
        YOUTUBE_PARTNER_SCOPE,
    }
    if not granted.intersection(playlist_write_scopes):
        fail(
            "Math YouTube OAuth token does not have playlist write permission. "
            "Run scripts/create_math_token.py again and replace the YOUTUBE_MATH_TOKEN_JSON "
            f"GitHub Actions secret before uploading. Required playlist: {DEFAULT_PLAYLIST_ID}."
        )


def ensure_video_in_playlist(youtube, video_id: str) -> dict:
    existing = youtube.playlistItems().list(
        part="id",
        playlistId=DEFAULT_PLAYLIST_ID,
        videoId=video_id,
        maxResults=50,
    ).execute()
    items = existing.get("items", [])
    if items:
        return {
            "playlist_id": DEFAULT_PLAYLIST_ID,
            "playlist_ok": True,
            "playlist_item_id": items[0].get("id"),
            "playlist_action": "already-present",
            "playlist_error": None,
        }

    response = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": DEFAULT_PLAYLIST_ID,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id,
                },
            }
        },
    ).execute()
    return {
        "playlist_id": DEFAULT_PLAYLIST_ID,
        "playlist_ok": True,
        "playlist_item_id": response.get("id"),
        "playlist_action": "inserted",
        "playlist_error": None,
    }


def playlist_needs_sync(record: dict | None) -> bool:
    if not record or not record.get("video_id"):
        return False
    return record.get("playlist_id") != DEFAULT_PLAYLIST_ID or record.get("playlist_ok") is not True


def existing_record_for(key: str, release_state: dict, history: dict) -> dict | None:
    return release_state["items"].get(key) or history["items"].get(key)


def check_existing_schedule(item: dict, existing: dict) -> None:
    old_publish_at = existing.get("publish_at")
    if old_publish_at and old_publish_at != item["publish_at"]:
        fail(
            f"Daily Math {item['number']} {item['type']} is already uploaded as "
            f"{existing.get('video_id')} with publishAt={old_publish_at}, but this Release "
            f"now requests publishAt={item['publish_at']}. Refusing to duplicate or silently reschedule."
        )


def persist_record(
    key: str,
    record: dict,
    args: argparse.Namespace,
    release_state_path: Path,
    release_state: dict,
    history_path: Path,
    history: dict,
) -> None:
    release_state["items"][key] = record
    history["items"][key] = record
    base.persist_confirmed_state(
        args.repo,
        args.release_tag,
        args.branch,
        release_state_path,
        release_state,
        history_path,
        history,
    )


def sync_playlist_or_fail(
    youtube,
    key: str,
    record: dict,
    args: argparse.Namespace,
    release_state_path: Path,
    release_state: dict,
    history_path: Path,
    history: dict,
) -> dict:
    try:
        playlist_payload = ensure_video_in_playlist(youtube, record["video_id"])
        record.update(playlist_payload)
        persist_record(
            key,
            record,
            args,
            release_state_path,
            release_state,
            history_path,
            history,
        )
        print(
            f"PLAYLIST CONFIRMED {record['number']} {record['type'].upper()}: "
            f"{DEFAULT_PLAYLIST_ID} ({record.get('playlist_action')})"
        )
        return record
    except Exception as exc:
        error_detail = base.http_error_detail(exc) if isinstance(exc, HttpError) else repr(exc)
        record.update({
            "playlist_id": DEFAULT_PLAYLIST_ID,
            "playlist_ok": False,
            "playlist_item_id": None,
            "playlist_action": "failed",
            "playlist_error": error_detail,
        })
        persist_record(
            key,
            record,
            args,
            release_state_path,
            release_state,
            history_path,
            history,
        )
        fail(
            f"Video {record['video_id']} is safely recorded, but adding it to playlist "
            f"{DEFAULT_PLAYLIST_ID} failed: {record['playlist_error']}"
        )


def run_main(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip).resolve()
    if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
        fail(f"ZIP not found: {zip_path}")

    release_body_path = Path(args.release_body).resolve()
    start_date = read_start_date(release_body_path)

    package_sha = base.sha256_file(zip_path)
    work = Path(args.workdir).resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    base.safe_extract(zip_path, work)
    root = base.package_root(work)

    print(f"Package: {zip_path.name}")
    print(f"SHA-256: {package_sha}")
    print(f"START_DATE: {start_date.isoformat()}")
    print(f"PAIR TIME: {PAIR_PUBLISH_TIME.strftime('%H:%M')} {SCHEDULE_TIMEZONE}")
    print(f"PLAYLIST: {DEFAULT_PLAYLIST_ID}")

    manifest = base.validate_package(root)
    manifest = add_schedule(manifest, start_date)
    print(f"PRE-FLIGHT PASSED: {len(manifest)//2} problems / {len(manifest)} videos")

    release_state_path = Path(args.release_state)
    history_path = Path(args.history)
    release_state = base.load_state(release_state_path)
    history = base.load_state(history_path)
    release_state["package_name"] = zip_path.name
    release_state["package_sha256"] = package_sha
    release_state["start_date"] = start_date.isoformat()
    release_state["timezone"] = SCHEDULE_TIMEZONE
    release_state["pair_publish_time"] = PAIR_PUBLISH_TIME.strftime("%H:%M")
    release_state["playlist_id"] = DEFAULT_PLAYLIST_ID

    needs_youtube = False
    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        existing = existing_record_for(key, release_state, history)
        if existing and existing.get("video_id"):
            check_existing_schedule(item, existing)
            print(
                f"SKIP {item['number']} {item['type'].upper()}: already uploaded as "
                f"{existing['video_id']} for {existing.get('scheduled_local') or existing.get('publish_at')}"
            )
            if playlist_needs_sync(existing):
                print(
                    f"PLAYLIST PENDING {item['number']} {item['type'].upper()}: "
                    f"{DEFAULT_PLAYLIST_ID}"
                )
                needs_youtube = True
        else:
            needs_youtube = True

    if needs_youtube:
        require_playlist_oauth_scope()
        youtube, channel_id = base.build_youtube_client()
    else:
        youtube, channel_id = None, None

    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        existing = existing_record_for(key, release_state, history)
        if existing and existing.get("video_id"):
            if playlist_needs_sync(existing):
                record = dict(existing)
                sync_playlist_or_fail(
                    youtube,
                    key,
                    record,
                    args,
                    release_state_path,
                    release_state,
                    history_path,
                    history,
                )
            continue

        print(
            f"UPLOAD {item['number']} {item['type'].upper()} -> "
            f"{item['scheduled_local']}: {item['title']}"
        )
        try:
            payload = upload_scheduled_item(youtube, channel_id, item)
        except HttpError as exc:
            fail(f"YouTube API upload failed: {base.http_error_detail(exc)}")

        record = {
            "package_name": zip_path.name,
            "package_sha256": package_sha,
            "number": item["number"],
            "type": item["type"],
            "title": item["title"],
            "video_id": payload.get("video_id"),
            "url": payload.get("url"),
            "privacy": "private",
            "youtube_status": "scheduled",
            "publish_at": payload.get("publish_at"),
            "scheduled_local": payload.get("scheduled_local"),
            "timezone": SCHEDULE_TIMEZONE,
            "channel": "math",
            "channel_id": payload.get("channel_id"),
            "thumbnail_requested": payload.get("thumbnail_requested"),
            "thumbnail_ok": payload.get("thumbnail_ok"),
            "thumbnail_error": payload.get("thumbnail_error"),
            "playlist_id": DEFAULT_PLAYLIST_ID,
            "playlist_ok": None,
            "playlist_item_id": None,
            "playlist_action": "pending",
            "playlist_error": None,
        }

        # Add the video to the playlist before moving to the next upload. If the playlist
        # API fails, sync_playlist_or_fail persists the confirmed video ID first, so a
        # resumed run will retry only the playlist step and will not duplicate the video.
        sync_playlist_or_fail(
            youtube,
            key,
            record,
            args,
            release_state_path,
            release_state,
            history_path,
            history,
        )
        print(
            f"CONFIRMED {item['number']} {item['type'].upper()}: "
            f"{record['video_id']} scheduled {record['scheduled_local']} playlist {DEFAULT_PLAYLIST_ID}"
        )

    print("SCHEDULING COMPLETE")
    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        record = existing_record_for(key, release_state, history) or {}
        print(
            json.dumps(
                {
                    "number": item["number"],
                    "type": item["type"],
                    "title": item["title"],
                    "video_id": record.get("video_id"),
                    "url": record.get("url"),
                    "scheduled_local": record.get("scheduled_local"),
                    "publish_at": record.get("publish_at"),
                    "privacy": record.get("privacy"),
                    "thumbnail_ok": record.get("thumbnail_ok"),
                    "playlist_id": record.get("playlist_id"),
                    "playlist_ok": record.get("playlist_ok"),
                },
                ensure_ascii=False,
            )
        )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a finished Daily Math master ZIP and schedule one Long+Short pair per day."
    )
    parser.add_argument("zip")
    parser.add_argument("--release-body", required=True)
    parser.add_argument("--release-tag")
    parser.add_argument("--repo")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--release-state", default="upload-state.json")
    parser.add_argument("--history", default="state/upload-history.json")
    parser.add_argument("--workdir", default=".work/package")
    args = parser.parse_args()
    try:
        raise SystemExit(run_main(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
