import errno
import os
import shutil
import subprocess
import sys
import tempfile


def numbered_destinations(destination):
    stem, extension = os.path.splitext(destination)
    yield destination
    number = 2
    while True:
        yield f"{stem} ({number}){extension}"
        number += 1


def publish_no_overwrite(source, destination):
    for candidate in numbered_destinations(destination):
        try:
            try:
                os.link(source, candidate)
            except OSError as exc:
                if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS):
                    raise
                created = False
                try:
                    with open(candidate, "xb") as output_file:
                        created = True
                        with open(source, "rb") as input_file:
                            shutil.copyfileobj(input_file, output_file)
                except BaseException:
                    if created:
                        os.unlink(candidate)
                    raise
            return candidate
        except FileExistsError:
            continue


def convert_file(source, target_extension, delete=False):
    destination = os.path.splitext(source)[0] + target_extension
    handle, temporary = tempfile.mkstemp(prefix=".music-organizer-", suffix=target_extension, dir=os.path.dirname(source))
    os.close(handle)
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", source, "-y", temporary],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed for {source}: {result.stderr.strip() or result.returncode}")
        if not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            raise RuntimeError(f"ffmpeg produced no output for {source}")
        output = publish_no_overwrite(temporary, destination)
        if delete:
            os.unlink(source)
        print(f"Converted {source} to {output}")
        return output
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _convert(directory, extensions, target_extension, delete=False, errors=None, skip=None, converted=None):
    failed_sources = set()
    for current, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(current, name))]
        for name in files:
            if os.path.splitext(name)[1].lower() not in extensions:
                continue
            source = os.path.join(current, name)
            if os.path.islink(source):
                continue
            try:
                if skip is not None and skip(source):
                    continue
                output = convert_file(source, target_extension, delete)
                if converted is not None and not delete:
                    converted[source] = output
            except (OSError, RuntimeError) as exc:
                if errors is None:
                    raise
                failed_sources.add(source)
                message = f"{source}: {exc}"
                print(f"Error: {message}", file=sys.stderr)
                errors.append(message)
    return failed_sources


def mp4_to_mp3(directory, delete=False, errors=None, skip=None, converted=None):
    return _convert(directory, {".mp4", ".m4a"}, ".mp3", delete, errors, skip, converted)


def aiff_to_flac(directory, delete=False, errors=None, skip=None, converted=None):
    return _convert(directory, {".aiff"}, ".flac", delete, errors, skip, converted)


def wav_to_flac(directory, delete=False, errors=None, skip=None, converted=None):
    return _convert(directory, {".wav"}, ".flac", delete, errors, skip, converted)


def wma_to_mp3(directory, delete=False, errors=None, skip=None, converted=None):
    return _convert(directory, {".wma"}, ".mp3", delete, errors, skip, converted)
