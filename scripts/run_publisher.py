#!/usr/bin/env python3
import publish_package

# Channel identity verification needs readonly in addition to upload.
publish_package.SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

if __name__ == "__main__":
    publish_package.main()
