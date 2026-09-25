# MusicOrganizer

Organize music files from their tags.

## Usage

Install Python dependencies with `python -m pip install -r requirements.txt` and make
sure `ffmpeg` is available on your PATH. Run:

```text
python main.py <directory> [delete]
```

### Optional Beets tagging

Install [Beets](https://docs.beets.io/) separately (`python -m pip install beets`),
ensure `beet` is on your PATH, and opt in with:

```text
python main.py <directory> [delete] --tag-with-beets
```

After conversion but before organization, this scans MP3 and FLAC files whose
artist (including album artist), album, **and** title are all blank. Only those
files are passed individually to Beets. With Beets' default matching settings,
strong recommendations (distance below `0.04`, roughly above 96% similarity)
are accepted; uncertain matches are skipped, not guessed or applied as-is. You
can adjust the cutoff with `match.strong_rec_thresh` in your Beets config.
Skipped files still go through the organizer's normal missing-tag fallbacks.
Original M4A, WMA, AIFF, and WAV files retained after conversion are not
tagged; their MP3/FLAC outputs are eligible. Files whose conversion failed are
not sent to Beets or moved by this run.

Beets is invoked in singleton, quiet mode with `-C -M` (no copy or move),
`--quiet-fallback skip`, and `-a -w` to enable autotagging and tag writing even
if those options are disabled in your Beets config. `-P` disables resuming
older imports. A bundled configuration
overlay disables duplicate replacement, remuxing, and link creation; it is
merged with your existing Beets config so your configured matching plugins and
library database still apply. Beets can update other metadata fields on
eligible files and adds accepted tracks to its database. Back up your music
first, and review any custom Beets plugins that may have their own side effects.
If Beets is missing or a tagging command fails, the opt-in run reports an error
and does not organize files; default runs require no Beets installation.

For genuinely tag-free tracks, enable acoustic matching in your Beets
`config.yaml` (find its location with `beet config -p`):

```yaml
plugins: musicbrainz chroma
```

Install `python -m pip install "beets[chroma]"`, the `fpcalc` executable from
[Chromaprint](https://acoustid.org/chromaprint) on your PATH, and an audio
decoder supported by Beets; MusicBrainz/AcoustID lookups need network access.
An AcoustID submission API key is **not** required for lookups. Alternatively,
Beets' `fromfilename` plugin can search based on filenames containing artist
and title. For review rather than automatic strong-match acceptance, run
`beet import -C -M -s -t <file>` manually (this is separate from the organizer).

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
