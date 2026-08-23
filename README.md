# Daily Math YouTube Publisher

Publisher-only automation for finished Daily Math video packages.

## What it does

1. Accepts one completed Daily Math master ZIP as a GitHub Release asset.
2. Reads one scheduling instruction from the Release description: `START_DATE=YYYY-MM-DD`.
3. Downloads and extracts the ZIP in GitHub Actions.
4. Performs a full-package preflight before any YouTube upload.
5. Reads exact Long/Short titles and descriptions from `Upload Helper.html`.
6. Uploads strictly in numerical order: `NNN Long`, then `NNN Short`.
7. Schedules each Long+Short pair for the exact same publish time.
8. Schedules the next Daily Math number one calendar day later.
9. Sends Long videos with their matching custom thumbnail.
10. Saves confirmed YouTube IDs and schedule data so a resumed run does not blindly duplicate uploads.

This repository does **not** create, render, edit, add music to, or otherwise modify supplied videos.

## Schedule rule

The schedule is intentionally simple and fixed:

- timezone: `America/Toronto`
- publish time: `10:00 AM`
- Long and Short for the same Daily Math number publish together at exactly the same time
- the next Daily Math number publishes one day later

Example Release description:

```text
START_DATE=2026-09-01
```

For a ZIP containing Daily Math 011 through 014, the resulting schedule is:

```text
011 Long  - 2026-09-01 10:00 America/Toronto
011 Short - 2026-09-01 10:00 America/Toronto
012 Long  - 2026-09-02 10:00 America/Toronto
012 Short - 2026-09-02 10:00 America/Toronto
013 Long  - 2026-09-03 10:00 America/Toronto
013 Short - 2026-09-03 10:00 America/Toronto
014 Long  - 2026-09-04 10:00 America/Toronto
014 Short - 2026-09-04 10:00 America/Toronto
```

Daylight-saving changes are handled by the `America/Toronto` timezone. The YouTube API receives the corresponding UTC `publishAt` timestamp.

The Release description must contain exactly one valid `START_DATE` line. The schedule is not stored inside the ZIP.

## ZIP size / video count

The number of problems in the ZIP is flexible. One problem, five problems, twenty-five problems, or another count are all acceptable as long as the package passes validation.

For every Daily Math number there must be exactly:

- one 1920x1080 Long MP4
- one 1080x1920 Short MP4
- one matching Long thumbnail
- one Long metadata entry
- one Short metadata entry

Problem numbers in a package must be consecutive.

## Normal use

1. Create a GitHub Release.
2. Put exactly one line like `START_DATE=2026-09-01` in the Release description.
3. Attach exactly one completed Daily Math master `.zip` file.
4. Publish the Release.

Publishing the Release triggers `.github/workflows/publish-math-package.yml` automatically.

The complete package and complete schedule are validated before the first upload. A preflight failure uploads nothing.

## YouTube scheduling behavior

Scheduled YouTube videos are uploaded with:

- `privacyStatus=private`
- `publishAt=<calculated UTC timestamp>`

YouTube automatically makes each video public at its scheduled time.

The workflow does not use `unlisted` for scheduled packages.

## One-time YouTube authorization

The Math publisher is independent from the finance/cooking publisher.

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

Preferred `Upload Helper.html` format includes an embedded machine-readable payload:

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

The workflow always uploads sequentially:

```text
011 Long
011 Short
012 Long
012 Short
...
```

Upload order and publish time are separate concepts. A Long and Short are uploaded one after the other, but YouTube receives the same `publishAt` value for that pair, so they become public together.

## Duplicate protection

Confirmed uploads are saved in two places:

1. `upload-state.json` attached back to the same GitHub Release
2. `state/upload-history.json` in the repository

The key includes the ZIP SHA-256, Daily Math number, and Long/Short type.

A resumed workflow skips an already-confirmed video only when its stored schedule matches the current Release schedule. If someone changes `START_DATE` after some videos were already uploaded, the workflow stops rather than silently duplicating or rescheduling them.

## Safety

- no upload starts until full package preflight passes
- the Release must contain a valid future `START_DATE`
- Long and Short for the same number use the exact same `publishAt`
- Shorts must be exactly 1080x1920 and 14.95–15.05 seconds
- Longs must be exactly 1920x1080
- titles/descriptions are never rewritten
- supplied MP4 files are never re-rendered
- the OAuth channel ID is verified before uploading
- a confirmed video ID is treated as success even if a later thumbnail step fails
- confirmed uploads and their schedules are persisted before moving to the next item
