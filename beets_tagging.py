"""Opt-in, in-place Beets tagging for files without identifying metadata."""

import os
from pathlib import Path
import subprocess
import sys

from mutagen import File, MutagenError


TAG_FIELDS = ("artist", "albumartist", "album", "title")
TAGGABLE_EXTENSIONS = {".mp3", ".flac"}
SAFE_CONFIG = Path(__file__).resolve().with_name("beets-safe-config.yaml")


def identifying_tags(path):
    audio = File(path, easy=True)
    if audio is None:
        return None
    tags = audio.tags
    if tags is None:
        return False
    return any(
        any(str(value).strip() for value in tags.get(field, []))
        for field in TAG_FIELDS
    )


def tag_untagged(directory, skip_sources, executable, inside_library):
    eligible = []
    for current, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            if os.path.splitext(name)[1].lower() not in TAGGABLE_EXTENSIONS:
                continue
            path = os.path.join(current, name)
            if path in skip_sources or os.path.islink(path) or not inside_library(directory, path):
                continue
            try:
                tagged = identifying_tags(path)
            except (OSError, MutagenError) as exc:
                print(f"Skipping unreadable audio {path}: {exc}", file=sys.stderr)
                continue
            if tagged is None:
                print(f"Skipping unrecognized audio {path}", file=sys.stderr)
            elif not tagged:
                eligible.append(path)

    print(f"Beets: found {len(eligible)} untagged MP3/FLAC files")
    tagged_count = 0
    for path in eligible:
        command = [
            executable, "--config", str(SAFE_CONFIG), "import",
            "-C", "-M", "-s", "-q", "-a", "-w", "-P",
            "--quiet-fallback", "skip", path,
        ]
        try:
            result = subprocess.run(
                command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Beets timed out while tagging {path}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
            raise RuntimeError(f"Beets failed for {path}: {detail}")
        after = identifying_tags(path)
        if after is None:
            raise RuntimeError(f"Beets left audio unreadable: {path}")
        if after:
            tagged_count += 1
            print(f"Beets tagged {path}")
        else:
            print(f"Beets skipped {path} (no confident match)")
            if result.stderr.strip():
                print(result.stderr.strip(), file=sys.stderr)
    print(f"Beets: tagged {tagged_count}, skipped {len(eligible) - tagged_count}")
