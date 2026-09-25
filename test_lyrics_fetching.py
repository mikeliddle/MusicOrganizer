import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mutagen.flac import FLAC
from mutagen.id3 import COMM, ID3, SYLT, TALB, TIT2, TPE1, TXXX, USLT

import lyrics_fetching
import main


class Backend:
    name = "test"

    def __init__(self, result):
        self.fetch = Mock(return_value=result)


class LyricsFetchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = Backend(SimpleNamespace(full_text="Synthetic test text", synced=False, sylt=[]))
        self.plugin = SimpleNamespace(backends=[self.backend])

    def audio(self, name, artist="Test artist", title="Test title", album="Test album"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = ["-c:a", "libmp3lame"] if path.suffix == ".mp3" else ["-c:a", "flac"]
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=mono", "-t", "2", *encoding, "-y", str(path)],
            check=True, capture_output=True,
        )
        if path.suffix == ".mp3":
            tags = ID3(path)
            if artist is not None:
                tags.add(TPE1(encoding=3, text=artist))
            if title is not None:
                tags.add(TIT2(encoding=3, text=title))
            if album is not None:
                tags.add(TALB(encoding=3, text=album))
            tags.save(path)
        else:
            tags = FLAC(path)
            if artist is not None:
                tags["artist"] = artist
            if title is not None:
                tags["title"] = title
            if album is not None:
                tags["album"] = album
            tags.save()
        return path

    def fetch(self, skip=()):
        with patch.dict(sys.modules, {"beetsplug.lyrics": SimpleNamespace(HTTPNotFoundError=LookupError)}):
            lyrics_fetching.fetch_missing_lyrics(str(self.root), skip, self.plugin, main.inside_library)

    def test_mp3_writes_uslt_only_and_rerun_is_no_op(self):
        path = self.audio("incoming/song.mp3")
        tags = ID3(path)
        tags.add(TXXX(encoding=3, desc="Original", text="unchanged"))
        tags.save(path)
        self.fetch()
        after = ID3(path)
        self.assertEqual("Synthetic test text", after.getall("USLT")[0].text)
        self.assertEqual("Test artist", after.getall("TPE1")[0].text[0])
        self.assertEqual("Test title", after.getall("TIT2")[0].text[0])
        self.assertEqual("unchanged", after.getall("TXXX")[0].text[0])
        original = path.read_bytes()
        self.fetch()
        self.assertEqual(original, path.read_bytes())
        self.backend.fetch.assert_called_once_with("Test artist", "Test title", "Test album", 2)
        self.assertEqual([path], list((self.root / "incoming").iterdir()))

    def test_flac_writes_lyrics_without_changing_other_fields(self):
        path = self.audio("incoming/song.flac")
        tags = FLAC(path)
        tags["custom"] = ["untouched"]
        tags.save()
        self.fetch()
        after = FLAC(path)
        self.assertEqual(["Synthetic test text"], after["lyrics"])
        self.assertEqual(["untouched"], after["custom"])
        self.assertEqual(["Test artist"], after["artist"])
        self.assertEqual(["Test title"], after["title"])

    def test_existing_lyrics_frames_and_fields_prevent_fetch(self):
        for frame in (
            USLT(encoding=3, lang="eng", desc="prior", text="Existing text"),
            SYLT(encoding=3, lang="eng", format=2, type=1, desc="prior", text=[("Prior", 1000)]),
            TXXX(encoding=3, desc="LyRiCs", text=["Existing text"]),
            COMM(encoding=3, lang="eng", desc="Lyrics:eng", text=["Existing text"]),
        ):
            path = self.audio(f"{type(frame).__name__}-{frame.HashKey[-4:]}.mp3")
            tags = ID3(path)
            tags.add(frame)
            tags.save(path)
        for field in ("LYRICS", "SYNCEDLYRICS", "UNSYNCEDLYRICS", "SYNCLYRICS", "LRC"):
            path = self.audio(f"{field}.flac")
            tags = FLAC(path)
            tags[field] = ["Existing text"]
            tags.save()
        before = {path: path.read_bytes() for path in self.root.iterdir()}
        self.fetch()
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.iterdir()})
        self.backend.fetch.assert_not_called()

    def test_missing_artist_or_title_skips_without_filename_guess(self):
        self.audio("artist-only.mp3", title=None)
        self.audio("title-only.flac", artist=None)
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.fetch()
        self.assertEqual(2, output.getvalue().count("missing artist or title"))
        self.backend.fetch.assert_not_called()

    def test_synced_result_adds_uslt_and_sylt_for_players(self):
        path = self.audio("timed.mp3")
        self.backend.fetch.return_value = SimpleNamespace(
            full_text="[00:01.00]Synthetic line", synced=True, sylt=[("Synthetic line", 1000)],
        )
        self.fetch()
        tags = ID3(path)
        self.assertEqual("[00:01.00]Synthetic line", tags.getall("USLT")[0].text)
        self.assertEqual([("Synthetic line", 1000)], tags.getall("SYLT")[0].text)

    def test_no_match_does_not_write_or_move(self):
        path = self.audio("incoming/song.flac")
        before = path.read_bytes()
        self.backend.fetch.return_value = None
        self.fetch()
        self.assertEqual(before, path.read_bytes())
        self.assertTrue(path.exists())

    def test_not_found_provider_tries_next_source(self):
        path = self.audio("song.mp3")
        first = Backend(None)
        first.fetch.side_effect = LookupError("no match")
        self.plugin.backends.insert(0, first)
        self.fetch()
        self.assertEqual("Synthetic test text", ID3(path).getall("USLT")[0].text)
        first.fetch.assert_called_once()

    def test_network_error_tries_next_source_and_reports_it(self):
        from requests import ConnectionError
        path = self.audio("song.flac")
        first = Backend(None)
        first.fetch.side_effect = ConnectionError("unavailable")
        self.plugin.backends.insert(0, first)
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.fetch()
        self.assertIn("provider errors", output.getvalue())
        self.assertEqual(["Synthetic test text"], FLAC(path)["lyrics"])

    def test_failed_conversion_and_symlinks_are_excluded(self):
        failed = self.audio("failed.mp3")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        other = Path(outside.name) / "outside.mp3"
        other.write_bytes(failed.read_bytes())
        try:
            (self.root / "link.mp3").symlink_to(other)
            (self.root / "linked").symlink_to(outside.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        before = other.read_bytes()
        self.fetch({str(failed)})
        self.backend.fetch.assert_not_called()
        self.assertEqual(before, other.read_bytes())

    def test_flag_standalone_and_combined_ordering(self):
        for flags in (["--fetch-lyrics"], ["delete", "--fetch-lyrics", "--tag-with-beets"]):
            with self.subTest(flags=flags):
                path = self.audio(f"{len(flags)}.mp3")
                steps = []
                with patch.object(main, "prepare_lyrics", return_value=self.plugin), patch.object(
                    main.shutil, "which", return_value="beet",
                ), patch.object(main, "tag_untagged", side_effect=lambda *args: steps.append("tag")), patch.object(
                    main, "fetch_missing_lyrics", side_effect=lambda *args: steps.append("lyrics"),
                ), patch.object(
                    main, "organize_files_by_artist_and_album", side_effect=lambda *args: steps.append("organize"),
                ):
                    self.assertEqual(0, main.main(["main.py", str(self.root), *flags]))
                self.assertEqual(
                    (["tag"] if "--tag-with-beets" in flags else []) + ["lyrics", "organize"], steps,
                )
                self.assertTrue(path.exists())

    def test_combined_flags_keep_preexisting_lyrics_out_of_tag_import(self):
        path = self.audio("incoming/lyriced.mp3", artist=None, title=None, album=None)
        tags = ID3(path)
        tags.add(USLT(encoding=3, lang="eng", desc="", text="Preexisting test text"))
        tags.save(path)
        before = path.read_bytes()
        with patch.dict(sys.modules, {"beetsplug.lyrics": SimpleNamespace(HTTPNotFoundError=LookupError)}), patch.object(
            main, "prepare_lyrics", return_value=self.plugin,
        ), patch.object(main.shutil, "which", return_value="beet"), patch.object(
            main, "tag_untagged",
        ) as tagging, patch.object(main, "organize_files_by_artist_and_album"):
            self.assertEqual(0, main.main([
                "main.py", str(self.root), "--tag-with-beets", "--fetch-lyrics",
            ]))
        self.assertIn(str(path), tagging.call_args.args[1])
        self.assertEqual(before, path.read_bytes())
        self.backend.fetch.assert_not_called()

    def test_lyrics_follow_conversion_and_history_tracks_written_output(self):
        source = self.root / "incoming" / "source.wav"
        source.parent.mkdir()
        source.write_bytes(b"source")
        calls = []

        def convert(directory, delete, errors, skip, converted):
            calls.append("convert")
            current_source = next(self.root.rglob("*.wav"))
            if skip is None or not skip(str(current_source)):
                # Produce a valid tagged conversion output without a network lookup.
                output = self.audio("incoming/source.flac")
                converted[str(current_source)] = str(output)
            return set()

        with patch.dict(sys.modules, {"beetsplug.lyrics": SimpleNamespace(HTTPNotFoundError=LookupError)}), patch.object(
            main, "prepare_lyrics", return_value=self.plugin,
        ), patch.object(main, "wav_to_flac", side_effect=convert):
            self.assertEqual(0, main.main(["main.py", str(self.root), "--fetch-lyrics"]))
            self.assertEqual(0, main.main(["main.py", str(self.root), "--fetch-lyrics"]))
        self.assertEqual(["convert", "convert"], calls)
        self.backend.fetch.assert_called_once()
        outputs = list(self.root.rglob("*.flac"))
        self.assertEqual(1, len(outputs))
        self.assertEqual(["Synthetic test text"], FLAC(outputs[0])["lyrics"])
        self.assertTrue((self.root / main.HISTORY_NAME).exists())

    def test_missing_dependency_or_provider_failure_stops_before_move(self):
        path = self.audio("incoming/song.mp3")
        with patch.object(main, "prepare_lyrics", side_effect=RuntimeError("Beets missing")), patch.object(
            main, "wav_to_flac",
        ) as conversion:
            self.assertEqual(1, main.main(["main.py", str(self.root), "delete", "--fetch-lyrics"]))
            conversion.assert_not_called()
        from requests import ConnectionError
        self.backend.fetch.side_effect = ConnectionError("provider unavailable")
        with patch.object(main, "prepare_lyrics", return_value=self.plugin), patch.object(
            main, "organize_files_by_artist_and_album",
        ) as move:
            with patch.dict(sys.modules, {"beetsplug.lyrics": SimpleNamespace(HTTPNotFoundError=LookupError)}):
                self.assertEqual(1, main.main(["main.py", str(self.root), "--fetch-lyrics"]))
            move.assert_not_called()
        self.assertTrue(path.exists())

    def test_delete_waits_for_lyrics_and_failed_lookup_reuses_conversion(self):
        from requests import ConnectionError
        source = self.root / "incoming" / "source.wav"
        source.parent.mkdir()
        source.write_bytes(b"source")
        produced = []

        def convert(directory, delete, errors, skip, converted):
            self.assertFalse(delete)
            if skip is None or not skip(str(source)):
                output = self.audio("incoming/source.flac")
                produced.append(output)
                converted[str(source)] = str(output)
            return set()

        with patch.dict(sys.modules, {"beetsplug.lyrics": SimpleNamespace(HTTPNotFoundError=LookupError)}), patch.object(
            main, "prepare_lyrics", return_value=self.plugin,
        ), patch.object(main, "wav_to_flac", side_effect=convert):
            self.backend.fetch.side_effect = ConnectionError("offline")
            self.assertEqual(1, main.main(["main.py", str(self.root), "delete", "--fetch-lyrics"]))
            self.assertTrue(source.exists())
            self.assertTrue(produced[0].exists())
            self.assertEqual(1, len(produced))
            self.assertTrue((self.root / main.HISTORY_NAME).exists())

            self.backend.fetch.side_effect = None
            self.assertEqual(0, main.main(["main.py", str(self.root), "--fetch-lyrics", "delete"]))
        self.assertEqual(1, len(produced))
        self.assertFalse(source.exists())
        outputs = list(self.root.rglob("*.flac"))
        self.assertEqual(1, len(outputs))
        self.assertEqual(["Synthetic test text"], FLAC(outputs[0])["lyrics"])

    def test_duplicate_flag_and_unknown_flags_are_rejected(self):
        for flags in (
            ["--fetch-lyrics", "--fetch-lyrics"],
            ["--fetch-lyrics", "--unknown"],
            ["delete", "delete", "--fetch-lyrics"],
        ):
            self.assertEqual(2, main.main(["main.py", str(self.root), *flags]))


if __name__ == "__main__":
    unittest.main()
