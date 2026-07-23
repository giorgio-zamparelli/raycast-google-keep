import importlib.util
import io
import json
import os
import pathlib
import stat
import tempfile
import unittest
from unittest.mock import patch


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


class FakeTextNote:
    type = None
    timestamps = FakeTimestamps()

    def __init__(self, note_id, title, text):
        self.id = note_id
        self.title = title
        self.text = text
        self.url = "https://keep.google.com/u/0/#NOTE/{}".format(note_id)


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

    def test_reads_a_legacy_manifest_without_a_pending_write_field(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            manifest = BRIDGE.new_mirror_manifest("person@example.com")
            manifest.pop("pendingWrite")
            manifest_path = directory / BRIDGE.MIRROR_MANIFEST_FILENAME
            manifest_path.write_text(json.dumps(manifest))
            os.chmod(manifest_path, 0o600)

            parsed_manifest = BRIDGE.read_mirror_manifest(directory)

            self.assertIsNone(parsed_manifest["pendingWrite"])

    def test_reads_versioned_request(self):
        original_stdin = BRIDGE.sys.stdin
        BRIDGE.sys.stdin = io.StringIO('{"version":1,"query":"DodoDentist"}')

        try:
            self.assertEqual(BRIDGE.read_request()["query"], "DodoDentist")
        finally:
            BRIDGE.sys.stdin = original_stdin

    def test_sync_writes_private_markdown_without_raw_note_id_in_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            note = FakeTextNote("note-1", "DodoDentist LLC", "Call the dentist\n~~~ keep this literal")

            result = BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")
            note_files = list(directory.glob("*.md"))
            manifest_path = directory / BRIDGE.MIRROR_MANIFEST_FILENAME
            manifest = json.loads(manifest_path.read_text())
            note_content = note_files[0].read_text()

            self.assertEqual(result["notes"], 1)
            self.assertEqual(result["written"], 1)
            self.assertEqual(len(note_files), 1)
            self.assertNotIn("note-1", note_files[0].name)
            self.assertIn("DodoDentist LLC", note_content)
            self.assertIn("~~~~text", note_content)
            self.assertNotIn("note-1", json.dumps(manifest))
            self.assertNotIn("person@example.com", json.dumps(manifest))
            self.assertNotIn("Call the dentist", json.dumps(manifest))
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(note_files[0].stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(manifest_path.stat().st_mode), 0o600)

    def test_sync_removes_only_stale_managed_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            first_note = FakeTextNote("note-1", "DodoDentist LLC", "First note")
            stale_note = FakeTextNote("note-2", "Old note", "Stale note")
            BRIDGE.sync_notes_to_mirror([first_note, stale_note], directory, "person@example.com")
            manual_file = directory / "manual-note.md"
            manual_file.write_text("This is not managed by the mirror.")

            result = BRIDGE.sync_notes_to_mirror([first_note], directory, "person@example.com")

            self.assertEqual(result["removed"], 1)
            self.assertTrue(manual_file.exists())
            self.assertEqual(len(list(directory.glob("*.md"))), 2)

    def test_sync_preserves_a_locally_changed_managed_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            note = FakeTextNote("note-1", "DodoDentist LLC", "Original note")
            BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")
            note_file = next(directory.glob("*.md"))
            note_file.write_text(note_file.read_text() + "Local edit")

            with self.assertRaises(BRIDGE.BridgeError) as raised:
                BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")

            self.assertEqual(raised.exception.code, "mirror-file-conflict")
            self.assertTrue(note_file.exists())

    def test_sync_preserves_a_locally_changed_stale_file(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            current_note = FakeTextNote("note-1", "DodoDentist LLC", "Current note")
            stale_note = FakeTextNote("note-2", "Old note", "Stale note")
            BRIDGE.sync_notes_to_mirror([current_note, stale_note], directory, "person@example.com")
            stale_file = directory / BRIDGE.mirror_filename(BRIDGE.note_hash("note-2"), "Old note")
            stale_file.write_text(stale_file.read_text() + "Local edit")

            with self.assertRaises(BRIDGE.BridgeError) as raised:
                BRIDGE.sync_notes_to_mirror([current_note], directory, "person@example.com")

            self.assertEqual(raised.exception.code, "mirror-file-conflict")
            self.assertTrue(stale_file.exists())
            self.assertTrue(stale_file.read_text().endswith("Local edit"))

    def test_sync_does_not_overwrite_an_unmanaged_file_with_a_matching_filename(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            note = FakeTextNote("note-1", "DodoDentist LLC", "Original note")
            collision_file = directory / BRIDGE.mirror_filename(BRIDGE.note_hash("note-1"), note.title)
            collision_file.write_text("Do not overwrite this local file.")

            with self.assertRaises(BRIDGE.BridgeError) as raised:
                BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")

            self.assertEqual(raised.exception.code, "mirror-file-conflict")
            self.assertEqual(collision_file.read_text(), "Do not overwrite this local file.")
            self.assertFalse((directory / BRIDGE.MIRROR_MANIFEST_FILENAME).exists())

    def test_sync_does_not_follow_a_replaced_mirror_symlink(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = pathlib.Path(temporary_directory)
            directory = temporary_root / "mirror"
            directory.mkdir(mode=0o700)
            note = FakeTextNote("note-1", "DodoDentist LLC", "Original note")
            BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")
            note_file = next(directory.glob("*.md"))
            outside_file = temporary_root / "outside-file.txt"
            outside_file.write_text("Do not modify this file.")
            note_file.unlink()
            os.symlink(outside_file, note_file)

            with self.assertRaises(BRIDGE.BridgeError) as raised:
                BRIDGE.sync_notes_to_mirror([note], directory, "person@example.com")

            self.assertEqual(raised.exception.code, "mirror-file-conflict")
            self.assertEqual(outside_file.read_text(), "Do not modify this file.")

    def test_sync_cleans_an_interrupted_extension_temp_file_before_writing_the_mirror(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            temporary_file = directory / "{}{}.tmp".format(BRIDGE.MIRROR_ATOMIC_TEMP_FILE_PREFIX, "a" * 32)
            temporary_file.write_text("Interrupted extension write")
            os.chmod(temporary_file, 0o600)

            result = BRIDGE.sync_notes_to_mirror(
                [FakeTextNote("note-1", "DodoDentist LLC", "Original note")],
                directory,
                "person@example.com",
            )

            self.assertEqual(result["notes"], 1)
            self.assertFalse(temporary_file.exists())
            self.assertEqual(len(list(directory.glob("*.md"))), 1)

    def test_first_sync_recovers_after_a_mid_transaction_replace_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            notes = [
                FakeTextNote("note-1", "DodoDentist LLC", "First note"),
                FakeTextNote("note-2", "Follow up", "Second note"),
            ]
            original_replace = BRIDGE.replace_staged_file
            replace_calls = 0

            def fail_second_replace(stage_file, target_file):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise BRIDGE.BridgeError("injected-failure", "Injected write failure")
                return original_replace(stage_file, target_file)

            with patch.object(BRIDGE, "replace_staged_file", side_effect=fail_second_replace):
                with self.assertRaises(BRIDGE.BridgeError) as raised:
                    BRIDGE.sync_notes_to_mirror(notes, directory, "person@example.com")

            self.assertEqual(raised.exception.code, "injected-failure")
            interrupted_manifest = json.loads((directory / BRIDGE.MIRROR_MANIFEST_FILENAME).read_text())
            self.assertIsNotNone(interrupted_manifest["pendingWrite"])
            self.assertEqual(len(list(directory.glob(".google-keep-search-stage-*"))), 1)

            result = BRIDGE.sync_notes_to_mirror(notes, directory, "person@example.com")
            recovered_manifest = json.loads((directory / BRIDGE.MIRROR_MANIFEST_FILENAME).read_text())

            self.assertEqual(result["notes"], 2)
            self.assertIsNone(recovered_manifest["pendingWrite"])
            self.assertEqual(recovered_manifest["pendingDeletion"], [])
            self.assertEqual(len(recovered_manifest["entries"]), 2)
            self.assertEqual(list(directory.glob(".google-keep-search-stage-*")), [])
            self.assertEqual(len(list(directory.glob("*.md"))), 2)

    def test_update_sync_recovers_after_a_mid_transaction_replace_failure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            original_notes = [
                FakeTextNote("note-1", "DodoDentist LLC", "Original first note"),
                FakeTextNote("note-2", "Follow up", "Original second note"),
            ]
            updated_notes = [
                FakeTextNote("note-1", "DodoDentist LLC", "Updated first note"),
                FakeTextNote("note-2", "Follow up", "Updated second note"),
            ]
            BRIDGE.sync_notes_to_mirror(original_notes, directory, "person@example.com")
            original_replace = BRIDGE.replace_staged_file
            replace_calls = 0

            def fail_second_replace(stage_file, target_file):
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 2:
                    raise BRIDGE.BridgeError("injected-failure", "Injected write failure")
                return original_replace(stage_file, target_file)

            with patch.object(BRIDGE, "replace_staged_file", side_effect=fail_second_replace):
                with self.assertRaises(BRIDGE.BridgeError) as raised:
                    BRIDGE.sync_notes_to_mirror(updated_notes, directory, "person@example.com")

            self.assertEqual(raised.exception.code, "injected-failure")
            interrupted_manifest = json.loads((directory / BRIDGE.MIRROR_MANIFEST_FILENAME).read_text())
            self.assertIsNotNone(interrupted_manifest["pendingWrite"])

            BRIDGE.sync_notes_to_mirror(updated_notes, directory, "person@example.com")
            recovered_manifest = json.loads((directory / BRIDGE.MIRROR_MANIFEST_FILENAME).read_text())
            note_contents = "\n".join(path.read_text() for path in directory.glob("*.md"))

            self.assertIsNone(recovered_manifest["pendingWrite"])
            self.assertEqual(recovered_manifest["pendingDeletion"], [])
            self.assertIn("Updated first note", note_contents)
            self.assertIn("Updated second note", note_contents)
            self.assertNotIn("Original first note", note_contents)
            self.assertNotIn("Original second note", note_contents)
            self.assertEqual(list(directory.glob(".google-keep-search-stage-*")), [])

    def test_reads_a_maximum_transaction_manifest_within_the_size_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)

            def make_entry(prefix, index):
                note_id_hash = BRIDGE.note_hash("{}-{}".format(prefix, index))
                return {
                    "noteHash": note_id_hash,
                    "filename": BRIDGE.mirror_filename(note_id_hash, "N" * BRIDGE.MIRROR_FILENAME_TITLE_BYTES),
                    "contentHash": BRIDGE.note_hash("content-{}-{}".format(prefix, index)),
                }

            entries = [make_entry("current", index) for index in range(BRIDGE.MIRROR_NOTE_LIMIT)]
            pending_deletion = [make_entry("stale", index) for index in range(BRIDGE.MIRROR_NOTE_LIMIT)]
            manifest = BRIDGE.new_mirror_manifest("person@example.com")
            manifest["entries"] = entries
            manifest["pendingDeletion"] = pending_deletion
            manifest["pendingWrite"] = {
                "stage": "{}{}".format(BRIDGE.MIRROR_STAGE_DIRECTORY_PREFIX, "a" * 32),
                "entries": entries,
            }
            serialized_manifest = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            manifest_path = directory / BRIDGE.MIRROR_MANIFEST_FILENAME
            manifest_path.write_text(serialized_manifest, encoding="utf-8")
            os.chmod(manifest_path, 0o600)

            self.assertLessEqual(
                len(serialized_manifest.encode("utf-8")),
                BRIDGE.MIRROR_MANIFEST_BYTES_LIMIT,
            )
            parsed_manifest = BRIDGE.read_mirror_manifest(directory)

            self.assertEqual(len(parsed_manifest["entries"]), BRIDGE.MIRROR_NOTE_LIMIT)
            self.assertEqual(len(parsed_manifest["pendingDeletion"]), BRIDGE.MIRROR_NOTE_LIMIT)
            self.assertEqual(len(parsed_manifest["pendingWrite"]["entries"]), BRIDGE.MIRROR_NOTE_LIMIT)
            self.assertEqual(parsed_manifest["entries"][0], entries[0])
            self.assertEqual(parsed_manifest["pendingDeletion"][-1], pending_deletion[-1])

    def test_sync_rejects_account_switch_and_clear_keeps_unmanaged_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = pathlib.Path(temporary_directory)
            note = FakeTextNote("note-1", "DodoDentist LLC", "Original note")
            BRIDGE.sync_notes_to_mirror([note], directory, "first@example.com")

            with self.assertRaises(BRIDGE.BridgeError) as raised:
                BRIDGE.sync_notes_to_mirror([note], directory, "second@example.com")
            self.assertEqual(raised.exception.code, "mirror-account-mismatch")

            manual_file = directory / "manual-note.md"
            manual_file.write_text("Keep this file.")
            with patch.object(BRIDGE, "default_mirror_directory", return_value=directory):
                result = BRIDGE.clear_mirror()

            self.assertEqual(result["removed"], 1)
            self.assertTrue(manual_file.exists())
            self.assertEqual(len(list(directory.glob("*.md"))), 1)

    def test_clear_rejects_a_path_traversal_manifest_without_touching_the_target(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = pathlib.Path(temporary_directory)
            directory = temporary_root / "mirror"
            directory.mkdir(mode=0o700)
            outside_file = temporary_root / "outside-file.md"
            outside_file.write_text("Do not delete this file.")
            manifest_path = directory / BRIDGE.MIRROR_MANIFEST_FILENAME
            malicious_manifest = {
                "kind": BRIDGE.MIRROR_MANIFEST_KIND,
                "version": BRIDGE.MIRROR_VERSION,
                "mirrorId": "a" * 32,
                "accountFingerprint": "b" * 64,
                "entries": [
                    {
                        "noteHash": "c" * 64,
                        "filename": "../outside-file.md",
                        "contentHash": "d" * 64,
                    }
                ],
                "pendingDeletion": [],
                "pendingWrite": None,
            }
            manifest_path.write_text(json.dumps(malicious_manifest))
            os.chmod(manifest_path, 0o600)

            with patch.object(BRIDGE, "default_mirror_directory", return_value=directory):
                with self.assertRaises(BRIDGE.BridgeError) as raised:
                    BRIDGE.clear_mirror()

            self.assertEqual(raised.exception.code, "mirror-manifest-invalid")
            self.assertTrue(manifest_path.exists())
            self.assertEqual(outside_file.read_text(), "Do not delete this file.")

    def test_clear_rejects_a_symlinked_mirror_directory_without_following_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = pathlib.Path(temporary_directory)
            target_directory = temporary_root / "target"
            target_directory.mkdir(mode=0o700)
            sentinel = target_directory / "sentinel.txt"
            sentinel.write_text("Do not touch this directory.")
            mirror_link = temporary_root / "mirror-link"
            os.symlink(target_directory, mirror_link)

            with patch.object(BRIDGE, "default_mirror_directory", return_value=mirror_link):
                with self.assertRaises(BRIDGE.BridgeError) as raised:
                    BRIDGE.clear_mirror()

            self.assertEqual(raised.exception.code, "mirror-directory-unsafe")
            self.assertEqual(sentinel.read_text(), "Do not touch this directory.")
            self.assertFalse((target_directory / BRIDGE.MIRROR_LOCK_FILENAME).exists())

    def test_mirror_filename_does_not_allow_path_traversal(self):
        filename = BRIDGE.mirror_filename(BRIDGE.note_hash("note-1"), "../../DodoDentist\x00 LLC")

        self.assertEqual(pathlib.Path(filename).name, filename)
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)


if __name__ == "__main__":
    unittest.main()
