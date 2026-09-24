import errno
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mutagen.id3 import ID3, TALB, TDRC, TIT2, TPE2, TYER

import convert
import main


class TemporaryLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, content=b"music"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


class OrganizerTests(TemporaryLibrary):
    def test_tags_year_missing_year_and_extension(self):
        self.write("incoming/first.MP3")
        self.write("incoming/second.flac")
        with patch.object(main, "EasyID3", return_value={
            "albumartist": ["Artist"], "album": ["Record"], "title": ["Track"], "date": ["2001-03-04"],
        }), patch.object(main, "FLAC", return_value={
            "artist": ["Other Artist"], "album": ["Yearless"], "title": ["FLAC song"],
        }):
            self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
        self.assertTrue((self.root / "Artist/Record (2001)/Track.MP3").exists())
        self.assertTrue((self.root / "Other Artist/Yearless/FLAC song.flac").exists())

    def test_reads_real_id3_date_and_legacy_year(self):
        for name, year_tag in (("date.mp3", TDRC(encoding=3, text=["2014-05-02"])),
                               ("legacy.mp3", TYER(encoding=3, text=["1997"]))):
            source = self.write(name, b"")
            tags = ID3()
            tags.add(TPE2(encoding=3, text=["Album Artist"]))
            tags.add(TALB(encoding=3, text=["Release"]))
            tags.add(TIT2(encoding=3, text=[name[:-4]]))
            tags.add(year_tag)
            tags.save(source)
        self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
        self.assertTrue((self.root / "Album Artist/Release (2014)/date.mp3").exists())
        self.assertTrue((self.root / "Album Artist/Release (1997)/legacy.mp3").exists())

    def test_missing_tags_and_unsafe_components_stay_inside_root(self):
        self.write("incoming/foo.bar.mp3")
        self.write("incoming/unsafe.flac")
        with patch.object(main, "EasyID3", side_effect=main.ID3NoHeaderError()), patch.object(
            main, "FLAC", return_value={
                "albumartist": ["../CON"], "album": ["..\\bad:*"], "title": ["../../NUL?"],
                "year": ["1998"],
            },
        ):
            self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/foo.bar.mp3").exists())
        self.assertTrue((self.root / "-CON/-bad-- (1998)/-..-NUL-.flac").exists())
        self.assertEqual(2, len(list(self.root.rglob("*.flac")) + list(self.root.rglob("*.mp3"))))

    def test_unbounded_collisions_and_second_run_is_idempotent(self):
        for number in range(12):
            self.write(f"incoming/{number}.mp3", str(number).encode())
        tags = {"albumartist": ["Artist"], "album": ["Album"], "title": ["Song"]}
        with patch.object(main, "EasyID3", return_value=tags):
            self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
            album = self.root / "Artist/Album"
            self.assertEqual(b"0", (album / "Song.mp3").read_bytes())
            for number in range(2, 13):
                self.assertTrue((album / f"Song ({number}).mp3").exists())
            before = {path.name: path.read_bytes() for path in album.iterdir()}
            self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
            self.assertEqual(before, {path.name: path.read_bytes() for path in album.iterdir()})

    def test_cleanup_removes_only_empty_descendants_without_following_links(self):
        self.write("old/nested/song.mp3")
        self.write("keep/note.txt")
        self.write("keep/track.wav")
        (self.root / "empty/deep").mkdir(parents=True)
        with patch.object(main, "EasyID3", return_value={
            "artist": ["Artist"], "album": ["Album"], "title": ["Song"],
        }):
            main.organize_files_by_artist_and_album(str(self.root))
        self.assertEqual([], main.remove_empty_subdirectories(str(self.root)))
        self.assertTrue(self.root.exists())
        self.assertFalse((self.root / "old").exists())
        self.assertFalse((self.root / "empty").exists())
        self.assertTrue((self.root / "keep/note.txt").exists())
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/track.wav").exists())
        self.assertTrue((self.root / "keep").exists())

    def test_symlink_destination_cannot_escape_root(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        try:
            (self.root / "Artist").symlink_to(outside.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable")
        source = self.write("incoming/song.mp3")
        with patch.object(main, "EasyID3", return_value={
            "artist": ["Artist"], "album": ["Album"], "title": ["Song"],
        }):
            errors = main.organize_files_by_artist_and_album(str(self.root))
        self.assertEqual(1, len(errors))
        self.assertTrue(source.exists())
        self.assertEqual([], list(Path(outside.name).iterdir()))
        main.remove_empty_subdirectories(str(self.root))
        self.assertTrue((self.root / "Artist").is_symlink())

    def test_external_symlinked_directory_is_not_traversed_or_cleaned(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        external = Path(outside.name) / "song.mp3"
        external.write_bytes(b"outside")
        try:
            (self.root / "linked").symlink_to(outside.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable")
        with patch.object(main, "EasyID3") as tags:
            self.assertEqual([], main.organize_files_by_artist_and_album(str(self.root)))
            self.assertEqual([], main.remove_empty_subdirectories(str(self.root)))
            tags.assert_not_called()
        self.assertEqual(b"outside", external.read_bytes())
        self.assertTrue((self.root / "linked").is_symlink())


class ConversionTests(TemporaryLibrary):
    def test_conversion_collisions_never_overwrite_and_delete_only_on_success(self):
        source = self.write("incoming/Track.wav", b"source")
        existing = self.write("incoming/Track.flac", b"existing")
        for number in range(2, 11):
            self.write(f"incoming/Track ({number}).flac", str(number).encode())

        def ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg):
            output = convert.convert_file(str(source), ".flac", delete=True)
        self.assertEqual(existing.read_bytes(), b"existing")
        self.assertEqual(Path(output).name, "Track (11).flac")
        self.assertEqual(Path(output).read_bytes(), b"converted")
        self.assertFalse(source.exists())
        self.assertEqual([], list((self.root / "incoming").glob(".music-organizer-*")))

    def test_failed_conversion_removes_partial_output_and_keeps_source(self):
        source = self.write("bad.wma")

        def ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "decoder failed")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg):
            with self.assertRaisesRegex(RuntimeError, "decoder failed"):
                convert.convert_file(str(source), ".mp3", delete=True)
        self.assertTrue(source.exists())
        self.assertFalse((self.root / "bad.mp3").exists())
        self.assertEqual([], list(self.root.glob(".music-organizer-*")))

    def test_main_reports_conversion_failure_and_preserves_original_path(self):
        source = self.write("incoming/bad.wma")

        def ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "decoder failed")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg):
            self.assertEqual(1, main.main(["main.py", str(self.root), "delete"]))
        self.assertEqual(source.read_bytes(), b"music")
        self.assertEqual([], list(self.root.rglob("*.mp3")))

    def test_publish_failure_keeps_source_without_touching_destination(self):
        source = self.write("source.mp3")
        destination = self.write("dest.mp3", b"existing")
        with patch.object(convert.os, "link", side_effect=OSError(errno.EACCES, "denied")):
            with self.assertRaises(PermissionError):
                convert.publish_no_overwrite(str(source), str(destination))
        self.assertEqual(b"existing", destination.read_bytes())
        self.assertEqual(b"music", source.read_bytes())

    def test_main_includes_wav_and_cleans_empty_source_without_delete(self):
        self.write("incoming/song.wav")

        def ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"flac")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg), patch.object(main, "FLAC", return_value={}):
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/song.wav").exists())
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/song.flac").exists())
        self.assertFalse((self.root / "incoming").exists())

    def test_main_rerun_with_retained_original_does_not_reconvert(self):
        self.write("incoming/song.wav")
        calls = []

        def ffmpeg(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg), patch.object(main, "FLAC", return_value={}):
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
            self.assertEqual(1, len(calls))
            original = self.root / "Unknown Artist/Unknown Album/song.wav"
            original.write_bytes(b"changed source")
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
        self.assertEqual(2, len(calls))
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/song (2).flac").exists())
        self.assertTrue((self.root / main.HISTORY_NAME).exists())

    def test_copy_failure_removes_partial_destination(self):
        source = self.write("original.mp3")

        def fail_copy(input_file, output_file):
            output_file.write(b"partial")
            raise OSError(errno.ENOSPC, "disk full")

        with patch.object(convert.os, "link", side_effect=OSError(errno.EXDEV, "other device")), patch.object(
            convert.shutil, "copyfileobj", side_effect=fail_copy,
        ):
            with self.assertRaises(OSError):
                convert.publish_no_overwrite(str(source), str(self.root / "new.mp3"))
        self.assertTrue(source.exists())
        self.assertFalse((self.root / "new.mp3").exists())

    def test_invalid_history_reports_error_without_modifying_music(self):
        source = self.write("incoming/song.wav")
        self.write(main.HISTORY_NAME, b"{invalid")
        with patch.object(convert.subprocess, "run") as ffmpeg:
            self.assertEqual(1, main.main(["main.py", str(self.root)]))
            ffmpeg.assert_not_called()
        self.assertTrue(source.exists())

    def test_history_cannot_follow_output_outside_root(self):
        source = self.write("incoming/song.wav")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        external = Path(outside.name) / "song.flac"
        external.write_bytes(b"existing")
        stat = source.stat()
        self.write(main.HISTORY_NAME, json.dumps({
            "incoming/song.wav": {
                "source": [stat.st_size, stat.st_mtime_ns, stat.st_ino],
                "output": os.path.relpath(external, self.root),
                "result": [external.stat().st_size, external.stat().st_mtime_ns, external.stat().st_ino],
            },
        }).encode())

        def ffmpeg(command, **kwargs):
            Path(command[-1]).write_bytes(b"converted")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(convert.subprocess, "run", side_effect=ffmpeg) as run, patch.object(
            main, "FLAC", return_value={},
        ):
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
            run.assert_called_once()
        self.assertEqual(b"existing", external.read_bytes())


if __name__ == "__main__":
    unittest.main()
