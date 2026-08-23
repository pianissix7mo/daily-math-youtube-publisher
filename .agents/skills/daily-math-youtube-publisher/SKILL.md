---
name: daily-math-youtube-publisher
description: Schedule a completed Daily Math master ZIP through the dedicated GitHub Release workflow. The ZIP is already finished media; never create, edit, re-render, or rewrite the videos or supplied metadata.
---

# Daily Math YouTube Publisher

Use this skill only for completed Daily Math packages.

## Core rule

This is a scheduler/publisher, not a video generator.

Never create, revise, re-render, resize, re-encode, add music to, or otherwise modify the supplied MP4 files or thumbnails.

Never rewrite the supplied YouTube titles or descriptions.

## Intake

The normal input is one completed Daily Math master ZIP attached as the only ZIP asset on a GitHub Release in:

`pianissix7mo/daily-math-youtube-publisher`

The Release description must contain exactly one line:

`START_DATE=YYYY-MM-DD`

Do not put schedule metadata inside the ZIP.

Publishing the Release triggers `.github/workflows/publish-math-package.yml`.

Do not commit large ZIP/MP4 files into Git history.

## Fixed schedule

- timezone: `America/Toronto`
- publish time: `10:00 AM`
- Long and Short for the same Daily Math number use the exact same YouTube `publishAt`
- the next Daily Math number is scheduled one calendar day later
- YouTube receives the corresponding UTC timestamp
- scheduled videos are uploaded as `private` with `publishAt`; YouTube makes them public automatically at that time

Example:

`START_DATE=2026-09-01`

means:

`011 Long + 011 Short -> 2026-09-01 10:00 Toronto`

`012 Long + 012 Short -> 2026-09-02 10:00 Toronto`

and so on.

The number of problem pairs inside the ZIP is flexible. The workflow schedules however many consecutive Daily Math pairs the package contains.

## Expected behavior

The workflow performs full-package and schedule preflight before the first upload, then uploads in exact order:

`NNN Long -> NNN Short -> next number`

Upload order is sequential, but each Long/Short pair shares the exact same scheduled public time.

Long videos receive the matching custom thumbnail.

Shorts do not receive the Long thumbnail.

The workflow uses only the isolated Math YouTube OAuth credentials stored in `YOUTUBE_MATH_TOKEN_JSON` and verifies them against `EXPECTED_MATH_CHANNEL_ID` before any upload.

Never use Finance or Cooking channel credentials for this workflow.

## Duplicate and schedule safety

Do not blindly retry an ambiguous upload.

Check the Release `upload-state.json` asset and repository `state/upload-history.json` when investigating a resume/retry.

A confirmed YouTube video ID means that video already exists even if a later thumbnail step failed.

An already-uploaded item may be skipped only when its stored `publishAt` matches the schedule currently derived from the Release `START_DATE`.

If `START_DATE` was changed after some videos were uploaded, stop rather than silently duplicating or rescheduling those videos.

## Reporting

After scheduling, report concisely:

- ZIP / Release tag
- package SHA-256
- START_DATE
- number range
- each Long/Short video ID and URL
- scheduled Toronto date/time / `publishAt`
- Long thumbnail status
- skipped duplicates or failures

Never print OAuth tokens, refresh tokens, client secrets, API keys, or other secret values.
