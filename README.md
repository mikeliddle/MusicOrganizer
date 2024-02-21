# MusicOrganizer

Organize music files

## File Conversion

This script converts mp4, m4a, and wma files to mp3. Aiff and wav get converted to flac. The script uses ffmpeg to convert the files. The script will also optionally remove the original files after conversion.

## File Organization

This script organizes the files into the following format based on metadata tags: `{albumartist}/{album}/{filename}`. It can also clean up empty folders following that.
