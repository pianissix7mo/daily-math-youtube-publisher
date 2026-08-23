#!/usr/bin/env python3
import schedule_package

schedule_package.base.SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

if __name__ == "__main__":
    schedule_package.main()
