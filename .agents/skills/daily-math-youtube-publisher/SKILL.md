---
name: daily-math-youtube-publisher
description: Publish a completed Daily Math master ZIP through the dedicated GitHub Release workflow. The ZIP is already finished media; never create, edit, re-render, or rewrite the videos or supplied metadata.
---

# Daily Math YouTube Publisher

Use this skill only for completed Daily Math packages.

## Core rule

This is a publisher, not a video generator.

Never create, revise, re-render, resize, re-encode, add music to, or otherwise modify the supplied MP4 files or thumbnails.

Never rewrite the supplied YouTube titles or descriptions.

## Normal user intent

Examples:

- `把这个数学 ZIP 上传 YouTube，按 math publisher 走`
- `upload the latest Daily Math package`
- `publish this finished math ZIP`

## Intake

The normal input is one completed Daily Math master ZIP.

Upload the ZIP as the only `.zip` asset on a GitHub Release in:

`pianissix7mo/daily-math-youtube-publisher`

Publishing the Release triggers `.github/workflows/publish-math-package.yml`.

Do not commit large ZIP/MP4 files into Git history.

## Default privacy

Use `unlisted` unless the user explicitly requests `private` or `public`.

Never infer `public` from the fact that the user asked to upload.

## Expected behavior

The workflow performs full-package preflight before the first upload, then publishes in exact order:

`NNN Long -> NNN Short -> next number`

Long videos receive the matching custom thumbnail.

Shorts do not receive the Long thumbnail.

The workflow uses only the isolated Math YouTube OAuth credentials stored in `YOUTUBE_MATH_TOKEN_JSON` and verifies them against `EXPECTED_MATH_CHANNEL_ID` before any upload.

Never use Finance or Cooking channel credentials for this workflow.

## Duplicate safety

Do not blindly retry an ambiguous upload.

Check the Release `upload-state.json` asset and repository `state/upload-history.json` when investigating a resume/retry.

A confirmed YouTube video ID means that video already exists even if a later thumbnail step failed.

## Reporting

After publishing, report concisely:

- ZIP / Release tag
- package SHA-256
- number range
- Long/Short upload status
- YouTube video IDs and URLs
- Long thumbnail status
- privacy
- any skipped duplicates or failures

Never print OAuth tokens, refresh tokens, client secrets, API keys, or other secret values.
