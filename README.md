# Daily Math YouTube Publisher

Publisher-only automation for finished Daily Math video packages.

## What it does

1. Accepts one completed Daily Math master ZIP as a GitHub Release asset.
2. Downloads and extracts the ZIP in GitHub Actions.
3. Performs a full-package preflight before any YouTube upload.
4. Reads exact Long/Short titles and descriptions from `Upload Helper.html`.
5. Uploads strictly in numerical order: `NNN Long`, then `NNN Short`.
6. Sends Long videos with their matching custom thumbnail.
7. Uploads directly to the dedicated Math YouTube channel using isolated OAuth credentials.
8. Defaults to `unlisted`.
9. Saves confirmed YouTube IDs so a resumed run does not blindly duplicate uploads.

This repository does **not** create, render, edit, add music to, or otherwise modify supplied videos.

## Normal use

Create a GitHub Release and attach exactly one Daily Math master `.zip` file. Publishing the Release triggers the workflow automatically.

The ZIP should contain:

- exactly one root-level `Upload Helper.html`
- exactly one root-level `Long Video Thumbnails` folder
- one root-level problem folder per Daily Math number
- exactly two MP4 files inside each problem folder: one 1920x1080 Long and one 1080x1920 Short
- one matching JPG/PNG thumbnail for every Long

The complete package is validated before the first upload. A preflight failure uploads nothing.

## One-time YouTube authorization

The Math publisher is intentionally independent from the finance/cooking publisher.

Create a Google OAuth **Desktop App** client with YouTube Data API v3 enabled, then run locally:

```bash
python -m pip install -r requirements.txt
python scripts/create_math_token.py path/to/client_secret.json
```

The helper requests both scopes required by the safety guard:

- `youtube.upload`
- `youtube.readonly`

It writes `token_math.json` locally and prints the authenticated channel ID.

Never commit `client_secret.json` or `token_math.json`.

## Required GitHub Actions secrets

Configure these two repository Actions secrets:

- `YOUTUBE_MATH_TOKEN_JSON` — paste the complete contents of `token_math.json`
- `EXPECTED_MATH_CHANNEL_ID` — paste the exact channel ID printed by the OAuth helper

Before the first `videos.insert`, the workflow calls `channels.list(mine=true)` and refuses to upload unless the authenticated channel exactly matches `EXPECTED_MATH_CHANNEL_ID`.

## Metadata contract

Preferred future `Upload Helper.html` format includes an embedded machine-readable payload:

```html
<script id="upload-data" type="application/json">
[
  {"number":"011","type":"long","title":"...","description":"..."},
  {"number":"011","type":"short","title":"...","description":"..."}
]
</script>
```

The parser also includes compatibility fallbacks for older helpers that store equivalent metadata in DOM data attributes or JavaScript objects.

## Upload order

The workflow always uploads:

```text
011 Long
011 Short
012 Long
012 Short
...
```

It never uploads all Longs first.

## Duplicate protection

Confirmed uploads are saved in two places:

1. `upload-state.json` attached back to the same GitHub Release
2. `state/upload-history.json` in the repository

The key includes the ZIP SHA-256, Daily Math number, and Long/Short type. A resumed workflow skips any item with an already-confirmed YouTube video ID.

## Safety

- default privacy is `unlisted`
- no upload starts until full preflight passes
- Shorts must be exactly 1080x1920 and 14.95–15.05 seconds
- Longs must be exactly 1920x1080
- titles/descriptions are never rewritten
- supplied MP4 files are never re-rendered
- the OAuth channel ID is verified before uploading
- a confirmed video ID is treated as success even if a later thumbnail step fails
- confirmed uploads are persisted before moving to the next item
