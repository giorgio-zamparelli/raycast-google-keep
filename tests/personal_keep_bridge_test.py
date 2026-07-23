import importlib.util
import io
import pathlib
import unittest


BRIDGE_PATH = pathlib.Path(__file__).parents[1] / "assets" / "personal-keep-bridge.py"
SPEC = importlib.util.spec_from_file_location("personal_keep_bridge", BRIDGE_PATH)
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)


class FakeTimestamp:
    def isoformat(self):
        return "2026-07-23T10:00:00+00:00"


class FakeNoteType:
    value = "LIST"


class FakeTimestamps:
    updated = FakeTimestamp()
    edited = None


class FakeNote:
    id = "note-1"
    title = "DodoDentist LLC"
    text = "Call the dentist to confirm an appointment."
    type = FakeNoteType()
    timestamps = FakeTimestamps()
    url = "https://keep.google.com/u/0/#LIST/note-1"


class PersonalKeepBridgeTest(unittest.TestCase):
    def test_scores_case_insensitive_multi_term_match(self):
        self.assertIsNotNone(BRIDGE.score_note("DodoDentist LLC", "Call the dentist", "dododentist llc"))
        self.assertIsNone(BRIDGE.score_note("DodoDentist LLC", "Call the dentist", "dododentist missing"))

    def test_serializes_preview_without_full_note_text(self):
        preview = BRIDGE.note_preview(FakeNote(), "dentist")

        self.assertEqual(preview["id"], "note-1")
        self.assertEqual(preview["title"], "DodoDentist LLC")
        self.assertTrue(preview["isList"])
        self.assertNotIn("text", preview)

    def test_reads_versioned_request(self):
        original_stdin = BRIDGE.sys.stdin
        BRIDGE.sys.stdin = io.StringIO('{"version":1,"query":"DodoDentist"}')

        try:
            self.assertEqual(BRIDGE.read_request()["query"], "DodoDentist")
        finally:
            BRIDGE.sys.stdin = original_stdin


if __name__ == "__main__":
    unittest.main()
