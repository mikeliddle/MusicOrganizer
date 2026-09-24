# MusicOrganizer

Organize music files from their tags.

## Usage

Install Python dependencies with `python -m pip install -r requirements.txt` and make
sure `ffmpeg` is available on your PATH. Run:

```text
python main.py <directory> [delete]
```

MP4/M4A and WMA are converted to MP3; AIFF and WAV are converted to FLAC.
Without `delete`, originals are retained. With `delete`, a source is removed
only after its conversion has succeeded and a nonempty output has been safely
published. Conversion and organization errors are reported and produce a nonzero exit status.

Supported media files are organized as
`AlbumArtist/Album (year)/TrackTitle.Extension`, using the `date` or `year`
tag from MP3/FLAC metadata for the year. Albums without a year use `Album`
without a suffix.
Missing album artist falls back to artist, then `Unknown Artist`; missing
album falls back to `Unknown Album`, and missing title to the filename stem.
Files without readable MP3 tags and formats without supported tag readers
use these fallbacks. Invalid path characters and Windows reserved names are
sanitized. Extensions retain their case; conversions use the output format's
extension.

Existing files are never overwritten: name collisions receive `(2)`, `(3)`,
and so on, with no fixed limit. Already-organized tracks retain their names.
When originals are retained, `.music-organizer-conversions.json` in the selected
directory tracks successful conversions so reruns do not make duplicates.
Changed sources or missing outputs are converted again.
Only empty subdirectories inside the selected directory are removed; files,
nonempty directories, and the selected directory are never deleted by cleanup.
