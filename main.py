import errno
import json
import os
import re
import shutil
import sys
import tempfile

from mutagen import MutagenError
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.id3 import ID3NoHeaderError

from convert import aiff_to_flac, mp4_to_mp3, publish_no_overwrite, wav_to_flac, wma_to_mp3
from beets_tagging import tag_untagged
from lyrics_fetching import existing_lyrics_paths, fetch_missing_lyrics, prepare_lyrics


MEDIA_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".flac", ".wma", ".aiff", ".wav"}
INVALID_COMPONENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
YEAR = re.compile(r"^(\d{4})(?:\D|$)")
HISTORY_NAME = ".music-organizer-conversions.json"


def parseArgs(args):
    if len(args) not in (2, 3) or (len(args) == 3 and args[2] != "delete"):
        raise ValueError("Usage: python main.py <directory> [delete] [--tag-with-beets] [--fetch-lyrics]")
    directory = os.path.abspath(args[1])
    if not os.path.isdir(directory) or os.path.islink(directory):
        raise ValueError(f"Not a directory (or is a link): {directory}")
    return directory, len(args) == 3


def report_error(errors, path, exc):
    message = f"{path}: {exc}"
    print(f"Error: {message}", file=sys.stderr)
    errors.append(message)


def inside_library(directory, path):
    absolute_root = os.path.abspath(directory)
    current = os.path.abspath(path)
    root = os.path.realpath(directory)
    candidate = os.path.realpath(path)
    try:
        if os.path.commonpath((absolute_root, current)) != absolute_root or os.path.commonpath((root, candidate)) != root:
            return False
    except ValueError:
        return False
    while os.path.normcase(current) != os.path.normcase(absolute_root):
        if os.path.islink(current):
            return False
        current = os.path.dirname(current)
    return True


def main(args):
    try:
        for flag in ("--tag-with-beets", "--fetch-lyrics"):
            if args[1:].count(flag) > 1:
                raise ValueError(f"Specify {flag} only once")
        use_beets = "--tag-with-beets" in args[1:]
        use_lyrics = "--fetch-lyrics" in args[1:]
        args = [args[0], *(arg for arg in args[1:] if arg not in ("--tag-with-beets", "--fetch-lyrics"))]
        directory, delete = parseArgs(args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    errors = []
    failed_sources = set()
    history_path = os.path.join(directory, HISTORY_NAME)
    try:
        with open(history_path, encoding="utf-8") as history_file:
            history = json.load(history_file)
        if not isinstance(history, dict):
            raise ValueError("Conversion history must be an object")
    except FileNotFoundError:
        history = {}
    except (OSError, ValueError) as exc:
        report_error(errors, history_path, exc)
        return 1
    if use_beets:
        beet = shutil.which("beet")
        if beet is None:
            report_error(errors, directory, "Beets not found on PATH; install beets or run without --tag-with-beets")
            return 1
    if use_lyrics:
        try:
            lyrics_plugin = prepare_lyrics()
        except (RuntimeError, ValueError) as exc:
            report_error(errors, directory, exc)
            return 1
    deferred_delete = delete and use_lyrics
    converted = {}

    def snapshot(path):
        info = os.stat(path)
        return [info.st_size, info.st_mtime_ns, info.st_ino]

    def skip_conversion(source):
        entry = history.get(os.path.relpath(source, directory))
        if not isinstance(entry, dict) or entry.get("source") != snapshot(source):
            return False
        output = entry.get("output")
        if not isinstance(output, str):
            return False
        output_path = os.path.join(directory, output)
        valid = (
            inside_library(directory, output_path)
            and os.path.isfile(output_path)
            and entry.get("result") == snapshot(output_path)
        )
        if valid and deferred_delete:
            converted[source] = output_path
        return valid

    for conversion in (mp4_to_mp3, aiff_to_flac, wav_to_flac, wma_to_mp3):
        failed_sources.update(conversion(
            directory, delete and not deferred_delete, errors,
            skip_conversion if deferred_delete or not delete else None, converted,
        ))
    tagging_failed = False
    if use_beets:
        try:
            protected = existing_lyrics_paths(directory, failed_sources, inside_library) if use_lyrics else set()
            if protected:
                print(f"Lyrics: preserving {len(protected)} already-lyriced files from Beets tagging")
            tag_untagged(directory, failed_sources | protected, beet, inside_library)
        except (OSError, RuntimeError, MutagenError) as exc:
            report_error(errors, directory, exc)
            tagging_failed = True
    if use_lyrics and not tagging_failed:
        try:
            fetch_missing_lyrics(directory, failed_sources, lyrics_plugin, inside_library)
        except (OSError, RuntimeError, MutagenError) as exc:
            report_error(errors, directory, exc)
            tagging_failed = True
    if deferred_delete and not tagging_failed:
        for source, output in converted.items():
            try:
                if not inside_library(directory, source) or not inside_library(directory, output):
                    raise ValueError("Conversion path left library root")
                if not os.path.isfile(source) or not os.path.isfile(output) or os.path.getsize(output) == 0:
                    raise ValueError("Converted source or output is missing")
                os.unlink(source)
            except (OSError, ValueError) as exc:
                report_error(errors, source, exc)
                tagging_failed = True
    moved = {}
    if not tagging_failed:
        organize_files_by_artist_and_album(directory, errors, failed_sources, moved)
        remove_empty_subdirectories(directory, errors)
    if (not delete or (deferred_delete and tagging_failed)) and (converted or (moved and history)):
        try:
            updated = {}
            for source, entry in history.items():
                if not isinstance(source, str) or not isinstance(entry, dict):
                    continue
                previous_source = os.path.join(directory, source)
                previous_output = entry.get("output")
                if not isinstance(previous_output, str):
                    continue
                current_source = moved.get(previous_source, previous_source)
                current_output = moved.get(os.path.join(directory, previous_output), os.path.join(directory, previous_output))
                if (
                    inside_library(directory, current_source)
                    and inside_library(directory, current_output)
                    and os.path.isfile(current_source)
                    and os.path.isfile(current_output)
                ):
                    updated[os.path.relpath(current_source, directory)] = {
                        "source": snapshot(current_source),
                        "output": os.path.relpath(current_output, directory),
                        "result": snapshot(current_output),
                    }
            for source, output in converted.items():
                current_source = moved.get(source, source)
                current_output = moved.get(output, output)
                if os.path.isfile(current_source) and os.path.isfile(current_output):
                    updated[os.path.relpath(current_source, directory)] = {
                        "source": snapshot(current_source),
                        "output": os.path.relpath(current_output, directory),
                        "result": snapshot(current_output),
                    }
            handle, temporary = tempfile.mkstemp(prefix=".music-organizer-history-", dir=directory)
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as history_file:
                    json.dump(updated, history_file, indent=2)
                os.replace(temporary, history_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except (OSError, ValueError) as exc:
            report_error(errors, history_path, exc)
    return 1 if errors else 0


def tag_value(tags, *keys):
    for key in keys:
        values = tags.get(key)
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    return None


def safe_component(value, fallback):
    component = INVALID_COMPONENT_CHARS.sub("-", value or "").strip().strip(". ")
    if not component or component in (".", ".."):
        component = fallback
    if WINDOWS_RESERVED_NAMES.fullmatch(component.split(".")[0]):
        component = f"_{component}"
    return component


def track_destination(root, source):
    extension = os.path.splitext(source)[1]
    tags = None
    if extension.lower() == ".mp3":
        try:
            tags = EasyID3(source)
        except ID3NoHeaderError:
            pass
    elif extension.lower() == ".flac":
        tags = FLAC(source)

    artist = safe_component(tag_value(tags, "albumartist", "artist") if tags else None, "Unknown Artist")
    album = safe_component(tag_value(tags, "album") if tags else None, "Unknown Album")
    title = safe_component(
        tag_value(tags, "title") if tags else None,
        safe_component(os.path.splitext(os.path.basename(source))[0], "Unknown Title"),
    )
    date = tag_value(tags, "date", "year") if tags else None
    match = YEAR.match(date) if date else None
    if match:
        album = f"{album} ({match.group(1)})"
    return os.path.join(root, artist, album), title + extension


def already_organized(source, destination_dir, name):
    if os.path.normcase(os.path.dirname(source)) != os.path.normcase(destination_dir):
        return False
    base, extension = os.path.splitext(name)
    stem, source_extension = os.path.splitext(os.path.basename(source))
    return source_extension.lower() == extension.lower() and (
        stem == base or re.fullmatch(rf"{re.escape(base)} \((?:[2-9]|[1-9]\d+)\)", stem) is not None
    )


def organize_files_by_artist_and_album(directory, errors=None, skip_sources=(), moved=None):
    errors = errors if errors is not None else []
    for current, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            if os.path.splitext(name)[1].lower() not in MEDIA_EXTENSIONS:
                continue
            source = os.path.join(current, name)
            if source in skip_sources or os.path.islink(source):
                continue
            try:
                destination_dir, destination_name = track_destination(directory, source)
                if already_organized(source, destination_dir, destination_name):
                    continue
                if not inside_library(directory, destination_dir):
                    raise ValueError(f"Destination escapes library root: {destination_dir}")
                os.makedirs(destination_dir, exist_ok=True)
                destination = publish_no_overwrite(source, os.path.join(destination_dir, destination_name))
                os.unlink(source)
                if moved is not None:
                    moved[source] = destination
                print(f"Moved {source} to {destination}")
            except (OSError, ValueError, MutagenError) as exc:
                report_error(errors, source, exc)
    return errors


def remove_empty_subdirectories(directory, errors=None):
    errors = errors if errors is not None else []
    for current, dirs, _ in os.walk(directory, topdown=False):
        for name in dirs:
            child = os.path.join(current, name)
            if os.path.islink(child):
                continue
            try:
                os.rmdir(child)
            except OSError as exc:
                if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                    report_error(errors, child, exc)
    return errors


if __name__ == "__main__":
    sys.exit(main(sys.argv))
