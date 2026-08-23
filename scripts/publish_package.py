#!/usr/bin/env python3
import argparse
import ast
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_JSON_ENV = "YOUTUBE_MATH_TOKEN_JSON"
EXPECTED_CHANNEL_ENV = "EXPECTED_MATH_CHANNEL_ID"
NUMBER_RE = re.compile(r"\b(\d{3})\b")
PROBLEM_DIR_RE = re.compile(r"^Daily Math (\d{3})\b", re.I)
VALID_PRIVACY = {"public", "private", "unlisted"}


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_json(cmd: list[str]) -> dict[str, Any]:
    return json.loads(subprocess.check_output(cmd, text=True))


def inspect_video(path: Path) -> dict[str, Any]:
    data = run_json([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name,pix_fmt:format=duration",
        "-of", "json", str(path),
    ])
    streams = data.get("streams") or []
    if not streams:
        fail(f"No readable video stream: {path.name}")
    stream = streams[0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": float(data["format"]["duration"]),
        "codec": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
    }


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if destination != target and destination not in target.parents:
                fail(f"Unsafe ZIP path: {member.filename}")
        zf.extractall(destination)


def decode_js_string(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"'):
        return json.loads(raw)
    if raw.startswith("'"):
        return ast.literal_eval(raw)
    if raw.startswith("`") and raw.endswith("`"):
        value = raw[1:-1]
        if "${" in value:
            fail("Upload Helper contains dynamic template metadata that cannot be parsed safely")
        return (value.replace("\\`", "`")
                     .replace("\\n", "\n")
                     .replace("\\r", "\r")
                     .replace("\\t", "\t")
                     .replace("\\\\", "\\"))
    return raw


def js_field(block: str, names: list[str]) -> str | None:
    for name in names:
        pattern = re.compile(
            rf"(?:[\"']?{re.escape(name)}[\"']?)\s*:\s*"
            r"(?P<v>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)",
            re.S,
        )
        match = pattern.search(block)
        if match:
            return decode_js_string(match.group("v"))
    return None


def normalize_meta_item(item: dict[str, Any]) -> tuple[tuple[str, str], dict[str, str]]:
    label = str(item.get("label", ""))
    number_value = str(item.get("number") or item.get("nnn") or item.get("id") or label)
    number_match = NUMBER_RE.search(number_value)
    if not number_match:
        fail(f"Metadata row has no three-digit Daily Math number: {item!r}")
    number = number_match.group(1)

    type_value = str(item.get("type") or item.get("kind") or label).lower()
    if "long" in type_value:
        kind = "long"
    elif "short" in type_value:
        kind = "short"
    else:
        fail(f"Metadata row has no Long/Short type for Daily Math {number}")

    title = str(item.get("title", "")).strip()
    description = str(item.get("description") or item.get("desc") or "").strip()
    if not title:
        fail(f"Metadata title is empty for {number} {kind}")
    if not description:
        fail(f"Metadata description is empty for {number} {kind}")
    if len(title) > 100:
        fail(f"YouTube title exceeds 100 characters for {number} {kind}")
    if len(description) > 5000:
        fail(f"YouTube description exceeds 5000 characters for {number} {kind}")
    return (number, kind), {
        "number": number,
        "type": kind,
        "title": title,
        "description": description,
    }


def parse_helper(helper_path: Path) -> dict[tuple[str, str], dict[str, str]]:
    text = helper_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(text, "html.parser")
    raw_items: list[dict[str, Any]] = []

    embedded = soup.find("script", id="upload-data")
    if embedded and embedded.string:
        payload = json.loads(embedded.string)
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("videos") or payload.get("entries")
        if not isinstance(payload, list):
            fail("#upload-data exists but does not contain a metadata list")
        raw_items.extend(x for x in payload if isinstance(x, dict))

    if not raw_items:
        for element in soup.find_all(attrs={"data-number": True}):
            attrs = element.attrs
            item = {
                "number": attrs.get("data-number"),
                "type": attrs.get("data-type") or attrs.get("data-kind"),
                "title": attrs.get("data-title"),
                "description": attrs.get("data-description") or attrs.get("data-desc"),
                "label": element.get_text(" ", strip=True),
            }
            if item["title"] and item["description"]:
                raw_items.append(item)

    if not raw_items:
        for script in soup.find_all("script"):
            source = script.string or script.get_text() or ""
            for block_match in re.finditer(r"\{[^{}]{20,}?\}", source, re.S):
                block = block_match.group(0)
                title = js_field(block, ["title"])
                description = js_field(block, ["description", "desc"])
                if not title or not description:
                    continue
                number = js_field(block, ["number", "nnn", "id"])
                kind = js_field(block, ["type", "kind"])
                label = js_field(block, ["label", "name"]) or ""
                raw_items.append({
                    "number": number or label,
                    "type": kind or label,
                    "title": title,
                    "description": description,
                    "label": label,
                })

    if not raw_items:
        fail(
            "Could not parse metadata from Upload Helper.html. "
            "Add the recommended embedded upload-data JSON payload."
        )

    metadata: dict[tuple[str, str], dict[str, str]] = {}
    errors: list[str] = []
    for item in raw_items:
        try:
            key, normalized = normalize_meta_item(item)
        except Exception as exc:
            errors.append(str(exc))
            continue
        if key in metadata and metadata[key] != normalized:
            fail(f"Conflicting duplicate metadata for {key[0]} {key[1]}")
        metadata[key] = normalized

    if not metadata:
        fail("Metadata candidates were found, but none could be normalized: " + "; ".join(errors[:5]))
    return metadata


def package_root(extracted: Path) -> Path:
    if (extracted / "Upload Helper.html").is_file():
        return extracted
    children = [p for p in extracted.iterdir() if p.is_dir()]
    files = [p for p in extracted.iterdir() if p.is_file()]
    if len(children) == 1 and not files and (children[0] / "Upload Helper.html").is_file():
        return children[0]
    return extracted


def validate_package(root: Path) -> list[dict[str, Any]]:
    helper_matches = list(root.rglob("Upload Helper.html"))
    if len(helper_matches) != 1 or helper_matches[0].parent != root:
        fail("ZIP must contain exactly one root-level Upload Helper.html")
    metadata = parse_helper(helper_matches[0])

    thumb_dir = root / "Long Video Thumbnails"
    if not thumb_dir.is_dir():
        fail("Missing root-level Long Video Thumbnails folder")

    problem_dirs: list[tuple[str, Path]] = []
    for path in root.iterdir():
        if not path.is_dir() or path.name == "Long Video Thumbnails":
            continue
        match = PROBLEM_DIR_RE.match(path.name)
        if match:
            problem_dirs.append((match.group(1), path))

    if not problem_dirs:
        fail("No Daily Math problem folders found")
    problem_dirs.sort(key=lambda x: int(x[0]))
    numbers = [n for n, _ in problem_dirs]
    if len(numbers) != len(set(numbers)):
        fail("Duplicate Daily Math problem folder number")
    expected = [f"{n:03d}" for n in range(int(numbers[0]), int(numbers[-1]) + 1)]
    if numbers != expected:
        fail(f"Daily Math numbers are not consecutive: found {numbers}, expected {expected}")

    thumbnails = [p for p in thumb_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if len(thumbnails) != len(problem_dirs):
        fail(f"Expected {len(problem_dirs)} Long thumbnails, found {len(thumbnails)}")

    manifest: list[dict[str, Any]] = []
    used_thumbs: set[Path] = set()

    for number, folder in problem_dirs:
        mp4s = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"]
        if len(mp4s) != 2:
            fail(f"Daily Math {number} folder must contain exactly two MP4 files; found {len(mp4s)}")
        for mp4 in mp4s:
            file_number = NUMBER_RE.search(mp4.name)
            if not file_number or file_number.group(1) != number:
                fail(f"MP4 numbering mismatch in Daily Math {number}: {mp4.name}")

        inspected = [(p, inspect_video(p)) for p in mp4s]
        longs = [(p, info) for p, info in inspected if info["width"] > info["height"]]
        shorts = [(p, info) for p, info in inspected if info["height"] > info["width"]]
        if len(longs) != 1 or len(shorts) != 1:
            fail(f"Daily Math {number} must contain exactly one landscape Long and one portrait Short")
        long_path, long_info = longs[0]
        short_path, short_info = shorts[0]

        if (long_info["width"], long_info["height"]) != (1920, 1080):
            fail(f"Daily Math {number} Long must be exactly 1920x1080; got {long_info['width']}x{long_info['height']}")
        if (short_info["width"], short_info["height"]) != (1080, 1920):
            fail(f"Daily Math {number} Short must be exactly 1080x1920; got {short_info['width']}x{short_info['height']}")
        if not 14.95 <= short_info["duration"] <= 15.05:
            fail(f"Daily Math {number} Short duration must be 14.95–15.05 seconds; got {short_info['duration']:.3f}")

        matching_thumbs = [p for p in thumbnails if re.search(rf"\bDaily Math {re.escape(number)}\b", p.name, re.I)]
        if len(matching_thumbs) != 1:
            fail(f"Daily Math {number} must have exactly one matching thumbnail; found {len(matching_thumbs)}")
        thumbnail = matching_thumbs[0]
        used_thumbs.add(thumbnail)

        for kind, path, thumb in (("long", long_path, thumbnail), ("short", short_path, None)):
            key = (number, kind)
            if key not in metadata:
                fail(f"Missing Upload Helper metadata for Daily Math {number} {kind}")
            meta = metadata[key]
            expected_prefix = f"Daily Math #{number}"
            if not meta["title"].startswith(expected_prefix):
                fail(f"Title number mismatch for {number} {kind}: {meta['title']}")
            manifest.append({
                "number": number,
                "type": kind,
                "path": str(path),
                "thumbnail": str(thumb) if thumb else None,
                "title": meta["title"],
                "description": meta["description"],
            })

    if len(used_thumbs) != len(thumbnails):
        extras = sorted(p.name for p in thumbnails if p not in used_thumbs)
        fail(f"Unexpected/unmatched thumbnail files: {extras}")

    expected_meta = {(n, t) for n in numbers for t in ("long", "short")}
    package_meta = {key for key in metadata if key[0] in numbers}
    if package_meta != expected_meta:
        missing = sorted(expected_meta - package_meta)
        extras = sorted(package_meta - expected_meta)
        fail(f"Upload Helper metadata mismatch. Missing={missing}, extras={extras}")

    manifest.sort(key=lambda x: (int(x["number"]), 0 if x["type"] == "long" else 1))
    return manifest


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "items": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items", {}), dict):
        fail(f"Invalid state file: {path}")
    data.setdefault("version", 1)
    data.setdefault("items", {})
    return data


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def gh_release_persist(repo: str, tag: str, state_path: Path) -> None:
    subprocess.run(["gh", "release", "upload", tag, str(state_path), "--clobber", "--repo", repo], check=True)


def gh_history_persist(repo: str, branch: str, history_path: Path, history: dict[str, Any]) -> None:
    write_state(history_path, history)
    current = run_json(["gh", "api", f"repos/{repo}/contents/{history_path.as_posix()}?ref={branch}"])
    sha = current["sha"]
    encoded = base64.b64encode(history_path.read_bytes()).decode("ascii")
    subprocess.run([
        "gh", "api", "--method", "PUT", f"repos/{repo}/contents/{history_path.as_posix()}",
        "-f", "message=Record confirmed Daily Math YouTube upload",
        "-f", f"content={encoded}", "-f", f"sha={sha}", "-f", f"branch={branch}",
    ], check=True, stdout=subprocess.DEVNULL)


def persist_confirmed_state(repo: str | None, tag: str | None, branch: str,
                            release_state_path: Path, release_state: dict[str, Any],
                            history_path: Path, history: dict[str, Any]) -> None:
    write_state(release_state_path, release_state)
    successes = 0
    errors: list[str] = []
    if repo and tag:
        try:
            gh_release_persist(repo, tag, release_state_path)
            successes += 1
        except Exception as exc:
            errors.append(f"Release state persistence failed: {exc}")
    if repo:
        try:
            gh_history_persist(repo, branch, history_path, history)
            successes += 1
        except Exception as exc:
            errors.append(f"Repository history persistence failed: {exc}")
    if repo and successes == 0:
        fail("Confirmed YouTube upload could not be durably recorded. " + " | ".join(errors))
    for error in errors:
        print(f"WARNING: {error}", file=sys.stderr)


def build_youtube_client():
    raw = os.getenv(TOKEN_JSON_ENV, "").strip()
    expected_channel = os.getenv(EXPECTED_CHANNEL_ENV, "").strip()
    if not raw:
        fail(f"Required GitHub Actions secret {TOKEN_JSON_ENV} is not configured")
    if not expected_channel:
        fail(f"Required GitHub Actions secret {EXPECTED_CHANNEL_ENV} is not configured")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{TOKEN_JSON_ENV} is not valid authorized-user JSON: {exc}")
    creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds.valid:
        fail("Math YouTube OAuth credentials are invalid")
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    response = youtube.channels().list(part="id", mine=True, maxResults=50).execute()
    channel_ids = sorted({item.get("id") for item in response.get("items", []) if item.get("id")})
    if len(channel_ids) != 1:
        fail(f"Math OAuth token must resolve to exactly one channel; got {channel_ids}")
    if channel_ids[0] != expected_channel:
        fail(
            f"Math OAuth channel mismatch: expected {expected_channel}, got {channel_ids[0]}. "
            "Upload stopped before videos.insert."
        )
    return youtube, channel_ids[0]


def http_error_detail(exc: HttpError) -> str:
    if isinstance(exc.content, bytes):
        return exc.content.decode("utf-8", errors="replace")
    return str(exc.content)


def upload_item(youtube, channel_id: str, item: dict[str, Any], privacy: str) -> dict[str, Any]:
    body = {
        "snippet": {
            "title": item["title"],
            "description": item["description"],
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(item["path"], mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
        notifySubscribers=False,
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status is not None:
            print(f"Upload progress {item['number']} {item['type']}: {int(status.progress() * 100)}%")
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
            thumbnail_error = http_error_detail(exc)

    return {
        "ok": True,
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy": privacy,
        "channel": "math",
        "channel_id": channel_id,
        "thumbnail_requested": thumbnail_requested,
        "thumbnail_ok": thumbnail_ok,
        "thumbnail_error": thumbnail_error,
    }


def run_main(args: argparse.Namespace) -> int:
    zip_path = Path(args.zip).resolve()
    if not zip_path.is_file() or zip_path.suffix.lower() != ".zip":
        fail(f"ZIP not found: {zip_path}")
    if args.privacy not in VALID_PRIVACY:
        fail("privacy must be public, private, or unlisted")

    package_sha = sha256_file(zip_path)
    work = Path(args.workdir).resolve()
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir(parents=True)
    safe_extract(zip_path, work)
    root = package_root(work)

    print(f"Package: {zip_path.name}")
    print(f"SHA-256: {package_sha}")
    manifest = validate_package(root)
    print(f"PRE-FLIGHT PASSED: {len(manifest)//2} problems / {len(manifest)} videos")

    release_state_path = Path(args.release_state)
    history_path = Path(args.history)
    release_state = load_state(release_state_path)
    history = load_state(history_path)
    release_state["package_name"] = zip_path.name
    release_state["package_sha256"] = package_sha

    pending = []
    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        existing = release_state["items"].get(key) or history["items"].get(key)
        if existing and existing.get("video_id"):
            print(f"SKIP {item['number']} {item['type'].upper()}: already uploaded as {existing['video_id']}")
        else:
            pending.append(item)

    if pending:
        youtube, channel_id = build_youtube_client()
    else:
        youtube, channel_id = None, None

    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        existing = release_state["items"].get(key) or history["items"].get(key)
        if existing and existing.get("video_id"):
            continue

        print(f"UPLOAD {item['number']} {item['type'].upper()}: {item['title']}")
        try:
            payload = upload_item(youtube, channel_id, item, args.privacy)
        except HttpError as exc:
            fail(f"YouTube API upload failed: {http_error_detail(exc)}")

        record = {
            "package_name": zip_path.name,
            "package_sha256": package_sha,
            "number": item["number"],
            "type": item["type"],
            "title": item["title"],
            "video_id": payload.get("video_id"),
            "url": payload.get("url"),
            "privacy": payload.get("privacy", args.privacy),
            "channel": "math",
            "channel_id": payload.get("channel_id"),
            "thumbnail_requested": payload.get("thumbnail_requested"),
            "thumbnail_ok": payload.get("thumbnail_ok"),
            "thumbnail_error": payload.get("thumbnail_error"),
        }
        release_state["items"][key] = record
        history["items"][key] = record
        persist_confirmed_state(
            args.repo, args.release_tag, args.branch,
            release_state_path, release_state, history_path, history,
        )
        print(f"CONFIRMED {item['number']} {item['type'].upper()}: {record['video_id']} {record['url']}")

    print("PUBLISH COMPLETE")
    for item in manifest:
        key = f"{package_sha}:{item['number']}:{item['type']}"
        record = release_state["items"].get(key) or history["items"].get(key) or {}
        print(json.dumps({
            "number": item["number"], "type": item["type"], "title": item["title"],
            "video_id": record.get("video_id"), "url": record.get("url"),
            "privacy": record.get("privacy"), "thumbnail_ok": record.get("thumbnail_ok"),
        }, ensure_ascii=False))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and publish one finished Daily Math master ZIP.")
    parser.add_argument("zip")
    parser.add_argument("--privacy", default="unlisted")
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
