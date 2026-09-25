"""Fetch missing embedded lyrics without importing or retagging tracks."""

import os
import sys

from mutagen import File, MutagenError
from mutagen.flac import FLAC
from mutagen.id3 import COMM, ID3, ID3NoHeaderError, SYLT, TXXX, USLT


LYRICS_FIELDS = {"LYRICS", "LYRIC", "UNSYNCEDLYRICS", "SYNCEDLYRICS", "SYNCLYRICS", "LRC"}


def lyric_field(name):
    return name.split(":", 1)[0].upper().replace("_", "").replace("-", "") in LYRICS_FIELDS


def prepare_lyrics():
    try:
        import confuse
        from beetsplug.lyrics import LyricsPlugin
    except ImportError as exc:
        raise RuntimeError(
            'Lyrics fetching requires Beets and its lyrics dependencies in this Python environment; '
            'install with python -m pip install "beets[lyrics]>=2.14.1"'
        ) from exc
    try:
        plugin = LyricsPlugin()
        if not plugin.backends:
            raise RuntimeError("Beets lyrics has no enabled sources; configure lyrics.sources in Beets")
    except confuse.ConfigError as exc:
        raise RuntimeError(f"Invalid Beets lyrics configuration: {exc}") from exc
    return plugin


def has_lyrics(tags):
    if isinstance(tags, ID3):
        return any(
            isinstance(frame, (USLT, SYLT))
            or isinstance(frame, (TXXX, COMM)) and lyric_field(frame.desc)
            for frame in tags.values()
        )
    return any(lyric_field(key) for key in tags)


def tag_text(tags, key):
    if isinstance(tags, ID3):
        frames = tags.getall(key)
        return str(frames[0].text[0]).strip() if frames and frames[0].text else ""
    return str(tags[key][0]).strip() if key in tags and tags[key] else ""


def read_track(path):
    if os.path.splitext(path)[1].lower() == ".mp3":
        try:
            return ID3(path)
        except ID3NoHeaderError:
            return None
    return FLAC(path)


def eligible_tracks(directory, skip_sources, inside_library):
    for current, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            if os.path.splitext(name)[1].lower() not in {".mp3", ".flac"}:
                continue
            path = os.path.join(current, name)
            if path not in skip_sources and not os.path.islink(path) and inside_library(directory, path):
                yield path


def existing_lyrics_paths(directory, skip_sources, inside_library):
    protected = set()
    for path in eligible_tracks(directory, skip_sources, inside_library):
        try:
            tags = read_track(path)
            if tags is not None and has_lyrics(tags):
                protected.add(path)
        except (OSError, MutagenError) as exc:
            raise RuntimeError(f"Lyrics check failed for {path}: {exc}") from exc
    return protected


def fetch_missing_lyrics(directory, skip_sources, plugin, inside_library):
    from beetsplug.lyrics import HTTPNotFoundError
    from requests import RequestException

    found = 0
    skipped = 0
    for path in eligible_tracks(directory, skip_sources, inside_library):
        try:
            tags = read_track(path)
            if tags is None:
                print(f"Lyrics: skipped {path} (no readable ID3 tags)", file=sys.stderr)
                skipped += 1
                continue
            if has_lyrics(tags):
                continue
            artist = tag_text(tags, "TPE1" if isinstance(tags, ID3) else "artist")
            title = tag_text(tags, "TIT2" if isinstance(tags, ID3) else "title")
            if not artist or not title:
                print(f"Lyrics: skipped {path} (missing artist or title tag)", file=sys.stderr)
                skipped += 1
                continue
            album = tag_text(tags, "TALB" if isinstance(tags, ID3) else "album")
            # LRCLib ranks candidates by track duration; do not use an
            # unknown duration as a match.
            audio = File(path)
            if audio is None or audio.info is None or audio.info.length <= 0:
                print(f"Lyrics: skipped {path} (no readable duration)", file=sys.stderr)
                skipped += 1
                continue
            duration = round(audio.info.length)
            lyrics = None
            provider_errors = []
            for backend in plugin.backends:
                try:
                    lyrics = backend.fetch(artist, title, album, duration)
                except HTTPNotFoundError:
                    continue
                except (RequestException, ValueError, TypeError, KeyError) as exc:
                    provider_errors.append(f"{backend.__class__.name}: {exc}")
                    continue
                if lyrics:
                    break
            if provider_errors:
                print(f"Lyrics: provider errors for {path}: {'; '.join(provider_errors)}", file=sys.stderr)
            if not lyrics or not lyrics.full_text.strip():
                if provider_errors:
                    raise RuntimeError(f"Lyrics lookup failed for {path}: {'; '.join(provider_errors)}")
                print(f"Lyrics: no match for {path}")
                skipped += 1
                continue
            if not inside_library(directory, path) or os.path.islink(path):
                raise RuntimeError(f"Lyrics file left library root: {path}")
            tags = read_track(path)
            if tags is None or has_lyrics(tags):
                print(f"Lyrics: skipped {path} (lyrics changed during lookup)", file=sys.stderr)
                skipped += 1
                continue
            if isinstance(tags, ID3):
                tags.add(USLT(encoding=3, lang="eng", desc="", text=lyrics.full_text))
                if lyrics.synced and lyrics.sylt:
                    tags.add(SYLT(encoding=3, lang="eng", format=2, type=1, desc="", text=lyrics.sylt))
                tags.save(path)
            else:
                tags["LYRICS"] = [lyrics.full_text]
                tags.save()
            found += 1
            print(f"Lyrics: embedded lyrics in {path}")
        except (OSError, MutagenError) as exc:
            raise RuntimeError(f"Lyrics failed for {path}: {exc}") from exc
    print(f"Lyrics: embedded {found}, skipped {skipped}")
