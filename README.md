# Daily Math YouTube Publisher

Publisher-only automation for finished Daily Math video packages.

## What it does

1. Accepts one completed Daily Math master ZIP as a GitHub Release asset.
2. Downloads and extracts the ZIP in GitHub Actions.
3. Performs a full-package preflight before any YouTube upload.
4. Reads exact Long/Short titles and descriptions from `Upload Helper.html`.
5. Uploads strictly in numerical order: `NNN Long`, then `NNN Short`.
6. Sends Long videos with their matching custom thumbnail.
7. Uses the dedicated YouTube publisher route `channel=math`.
8. Defaults to `unlisted`.
9. Saves confirmed YouTube IDs so a resumed run does not blindly duplicate uploads.

This repository does **not** create, render, edit, add music to, or otherwise modify supplied videos.

## Normal use

Create a GitHub Release and attach exactly one Daily Math master `.zip` file. Publishing the Release triggers the workflow automatically.

The ZIP should contain:

- exactly one root-level `Upload Helper.html`
- exactly one root-level `Long Video Thumbnails` folder
- one root-level problem folder per Daily Math number
- exactly two MP4 files inside each problem folder: one landscape Long and one portrait Short
- one matching JPG/PNG thumbnail for every Long

The complete package is validated before the first upload. A preflight failure uploads nothing.

## Required GitHub Actions secret

`YOUTUBE_PUBLISHER_MCP_TOKEN`

This is the bearer token used to request short-lived upload URLs from the existing hosted `youtube-cloud-publisher` service. Never commit it to this repository.

## Required publisher configuration

The hosted `youtube-cloud-publisher` must expose a dedicated `math` route with its own OAuth token and expected-channel guard:

- `YOUTUBE_MATH_TOKEN_PATH=/etc/secrets/token_math.json`
- `EXPECTED_MATH_CHANNEL_ID=<the math channel ID>`

The math route must never fall back to finance or cooking credentials.

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

## Safety

- default privacy is `unlisted`
- no upload starts until full preflight passes
- Shorts must be portrait and 14.95–15.05 seconds
- Longs must be landscape
- titles/descriptions are never rewritten
- supplied MP4 files are never re-rendered
- a confirmed video ID is treated as success even if a later thumbnail step fails
- confirmed uploads are persisted to the Release state asset and repository history before moving to the next item
