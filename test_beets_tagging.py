import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import beets_tagging
import main


class BeetsTaggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"music")
        return str(path)

    def test_only_fully_untagged_audio_is_imported_in_place(self):
        empty = self.write("incoming/empty.mp3")
        tagged = self.write("incoming/tagged.mp3")
        partial = self.write("incoming/partial.flac")
        failed = self.write("incoming/failed.flac")
        self.write("incoming/not-a-track.txt")
        metadata = {
            empty: {},
            tagged: {"artist": ["Artist"], "album": ["Album"], "title": ["Song"]},
            partial: {"albumartist": ["Artist"]},
            failed: {},
        }

        def run(command, **kwargs):
            self.assertEqual(empty, command[-1])
            metadata[empty] = {"artist": ["Matched artist"], "title": ["Matched title"]}
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(
            beets_tagging, "File",
            side_effect=lambda path, easy: SimpleNamespace(tags=metadata[path]),
        ) as read, patch.object(beets_tagging.subprocess, "run", side_effect=run) as invoked:
            beets_tagging.tag_untagged(str(self.root), {failed}, "beet", main.inside_library)
        self.assertEqual(1, invoked.call_count)
        command = invoked.call_args.args[0]
        self.assertEqual(
            ["beet", "--config", str(beets_tagging.SAFE_CONFIG), "import",
             "-C", "-M", "-s", "-q", "-a", "-w", "-P",
             "--quiet-fallback", "skip", empty],
            command,
        )
        self.assertEqual(subprocess.DEVNULL, invoked.call_args.kwargs["stdin"])
        self.assertTrue(beets_tagging.SAFE_CONFIG.is_file())
        safe_config = beets_tagging.SAFE_CONFIG.read_text(encoding="utf-8")
        self.assertIn("duplicate_action: skip", safe_config)
        self.assertIn("remux_mp3_in_wav: no", safe_config)
        self.assertIn("from_scratch: no", safe_config)
        self.assertEqual({empty, tagged, partial}, {call.args[0] for call in read.call_args_list})

    def test_no_confident_match_leaves_tags_untouched(self):
        self.write("song.flac")
        with patch.object(beets_tagging, "File", return_value=SimpleNamespace(tags={})), patch.object(
            beets_tagging.subprocess, "run",
            return_value=subprocess.CompletedProcess(["beet"], 0, "", ""),
        ) as invoked:
            beets_tagging.tag_untagged(str(self.root), set(), "beet", main.inside_library)
        invoked.assert_called_once()

    def test_failed_beets_import_reports_failure(self):
        self.write("song.mp3")
        with patch.object(beets_tagging, "File", return_value=SimpleNamespace(tags={})), patch.object(
            beets_tagging.subprocess, "run",
            return_value=subprocess.CompletedProcess(["beet"], 3, "", "network unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                beets_tagging.tag_untagged(str(self.root), set(), "beet", main.inside_library)

    def test_beets_leaving_audio_unreadable_reports_failure(self):
        self.write("song.flac")
        reads = iter((SimpleNamespace(tags={}), None))
        with patch.object(beets_tagging, "File", side_effect=lambda *args, **kwargs: next(reads)), patch.object(
            beets_tagging.subprocess, "run",
            return_value=subprocess.CompletedProcess(["beet"], 0, "", ""),
        ):
            with self.assertRaisesRegex(RuntimeError, "left audio unreadable"):
                beets_tagging.tag_untagged(str(self.root), set(), "beet", main.inside_library)

    def test_beets_timeout_reports_failure(self):
        self.write("song.mp3")
        with patch.object(beets_tagging, "File", return_value=SimpleNamespace(tags={})), patch.object(
            beets_tagging.subprocess, "run", side_effect=subprocess.TimeoutExpired(["beet"], 300),
        ):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                beets_tagging.tag_untagged(str(self.root), set(), "beet", main.inside_library)

    def test_opt_out_and_missing_executable(self):
        self.write("song.mp3")
        with patch.object(main, "tag_untagged") as tag, patch.object(main.shutil, "which", return_value=None):
            self.assertEqual(0, main.main(["main.py", str(self.root)]))
            self.assertEqual(1, main.main(["main.py", str(self.root), "--tag-with-beets"]))
            tag.assert_not_called()
        self.assertTrue((self.root / "Unknown Artist/Unknown Album/song.mp3").exists())

    def test_missing_beets_stops_before_conversion(self):
        source = self.write("song.wav")
        with patch.object(main.shutil, "which", return_value=None), patch.object(
            main, "wav_to_flac",
        ) as convert:
            self.assertEqual(1, main.main(["main.py", str(self.root), "--tag-with-beets"]))
            convert.assert_not_called()
        self.assertTrue(Path(source).exists())

    def test_beets_runs_after_conversion_and_before_organization(self):
        song = self.write("song.wav")
        output = str(self.root / "song.flac")
        failed = self.write("failed.flac")
        calls = []

        def conversion(directory, delete, errors, skip, converted):
            calls.append("convert")
            Path(output).write_bytes(b"converted")
            converted[song] = output
            return {failed}

        def tag(directory, skip_sources, executable, inside_library):
            calls.append("tag")
            self.assertEqual({failed}, skip_sources)
            self.assertEqual("beet", executable)
            self.assertIs(main.inside_library, inside_library)
            self.assertTrue(Path(output).exists())

        with patch.object(main.shutil, "which", return_value="beet"), patch.object(
            main, "mp4_to_mp3", side_effect=conversion,
        ), patch.object(main, "aiff_to_flac", return_value=set()), patch.object(
            main, "wav_to_flac", return_value=set(),
        ), patch.object(main, "wma_to_mp3", return_value=set()), patch.object(
            main, "tag_untagged", side_effect=tag,
        ), patch.object(main, "organize_files_by_artist_and_album", side_effect=lambda *args: calls.append("organize")), patch.object(
            main, "remove_empty_subdirectories", side_effect=lambda *args: calls.append("cleanup"),
        ):
            self.assertEqual(0, main.main(["main.py", str(self.root), "--tag-with-beets"]))
        self.assertEqual(["convert", "tag", "organize", "cleanup"], calls)

    def test_beets_failure_stops_organization_and_keeps_conversion_history(self):
        source = self.write("incoming/song.wav")
        output = self.write("incoming/song.flac")

        def conversion(directory, delete, errors, skip, converted):
            converted[source] = output
            return set()

        with patch.object(main.shutil, "which", return_value="beet"), patch.object(
            main, "wav_to_flac", side_effect=conversion,
        ), patch.object(main, "tag_untagged", side_effect=RuntimeError("bad match service")), patch.object(
            main, "organize_files_by_artist_and_album",
        ) as organize:
            self.assertEqual(1, main.main(["main.py", str(self.root), "--tag-with-beets"]))
            organize.assert_not_called()
        self.assertTrue(Path(output).exists())
        history = json.loads((self.root / main.HISTORY_NAME).read_text(encoding="utf-8"))
        self.assertEqual(
            os.path.relpath(output, self.root),
            history[os.path.relpath(source, self.root)]["output"],
        )

    def test_invalid_flag_count_is_rejected(self):
        self.assertEqual(
            2,
            main.main(["main.py", str(self.root), "--tag-with-beets", "--tag-with-beets"]),
        )


if __name__ == "__main__":
    unittest.main()
