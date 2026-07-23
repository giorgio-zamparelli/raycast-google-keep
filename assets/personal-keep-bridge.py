#!/usr/bin/env python3
"""Local-only bridge for the experimental personal Google Keep Raycast command.

This deliberately talks only to gkeepapi. It never receives a Google password
and emits structured JSON without tracebacks. Search itself does not persist
notes; the explicit root-search mirror command is the only opt-in exception.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import getpass
import hashlib
import importlib.util
import json
import logging
import os
import platform
import re
import secrets
import stat
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


PROTOCOL_VERSION = 1
MINIMUM_PYTHON = (3, 10)
TOKEN_SERVICE = "com.giorgio-zamparelli.raycast-google-keep.poc.master-token"
ACTIVE_ACCOUNT_SERVICE = "com.giorgio-zamparelli.raycast-google-keep.poc.active-account"
DEVICE_ID_SERVICE = "com.giorgio-zamparelli.raycast-google-keep.poc.device-id"
ACTIVE_ACCOUNT_NAME = "active"
MAX_QUERY_LENGTH = 500
MAX_RESULTS = 100
SNIPPET_LENGTH = 220
MAX_DETAIL_LENGTH = 250_000
MIRROR_DIRECTORY_NAME = "Google Keep Search"
MIRROR_MANIFEST_FILENAME = ".google-keep-search-mirror.json"
MIRROR_LOCK_FILENAME = ".google-keep-search-mirror.lock"
MIRROR_STAGE_DIRECTORY_PREFIX = ".google-keep-search-stage-"
MIRROR_STAGE_FILE_SUFFIX = ".tmp"
MIRROR_ATOMIC_TEMP_FILE_PREFIX = ".google-keep-search-"
MIRROR_MANIFEST_KIND = "google-keep-search-mirror"
MIRROR_VERSION = 1
MIRROR_FILE_PREFIX = "Google Keep — "
MIRROR_FILE_SUFFIX = ".md"
MIRROR_FILENAME_TITLE_BYTES = 160
MIRROR_NOTE_LIMIT = 10_000
MIRROR_NOTE_BYTES_LIMIT = 500_000
MIRROR_TOTAL_BYTES_LIMIT = 100_000_000
MIRROR_FILE_BYTES_LIMIT = 600_000
MIRROR_MANIFEST_BYTES_LIMIT = 16_000_000


class BridgeError(Exception):
    """A safe, user-actionable bridge error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps({"version": PROTOCOL_VERSION, **payload}, ensure_ascii=False, separators=(",", ":")))


def fail(code: str, message: str) -> int:
    emit({"ok": False, "error": {"code": code, "message": message}})
    return 1


def supported_python() -> bool:
    return sys.version_info >= MINIMUM_PYTHON


def python_version() -> str:
    return ".".join(str(part) for part in sys.version_info[:3])


def require_supported_python() -> None:
    if not supported_python():
        raise BridgeError(
            "unsupported-python",
            "The personal Keep proof of concept requires Python 3.10 or newer. "
            "Set the extension's Personal Keep Python Executable preference to a suitable virtual environment.",
        )


def dependency_status() -> Dict[str, bool]:
    return {
        "gkeepapi": importlib.util.find_spec("gkeepapi") is not None,
        "keyring": importlib.util.find_spec("keyring") is not None,
    }


def require_keyring() -> Any:
    if platform.system() != "Darwin":
        raise BridgeError("unsupported-platform", "This proof of concept currently requires macOS Keychain.")

    if not dependency_status()["keyring"]:
        raise BridgeError("dependencies-missing", "Install the pinned personal Keep companion dependencies first.")

    import keyring  # pylint: disable=import-outside-toplevel

    backend = keyring.get_keyring()
    backend_module = type(backend).__module__

    if not backend_module.startswith("keyring.backends.macOS"):
        raise BridgeError(
            "keychain-unavailable",
            "The personal Keep proof of concept requires keyring's macOS Keychain backend.",
        )

    return keyring


def keychain_status() -> Dict[str, bool]:
    if not supported_python() or not dependency_status()["keyring"] or platform.system() != "Darwin":
        return {"available": False, "configured": False}

    try:
        keyring = require_keyring()
        email = keyring.get_password(ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)
        token = keyring.get_password(TOKEN_SERVICE, email) if email else None
        device_id = keyring.get_password(DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME)
        return {"available": True, "configured": bool(email and token and device_id)}
    except Exception:  # Keychain failures must not leak implementation details or credentials.
        return {"available": False, "configured": False}


def delete_password(keyring: Any, service: str, username: str) -> None:
    try:
        keyring.delete_password(service, username)
    except keyring.errors.PasswordDeleteError:
        pass


def active_credentials() -> Dict[str, str]:
    keyring = require_keyring()
    email = keyring.get_password(ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)
    device_id = keyring.get_password(DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME)

    if not email or not device_id:
        raise BridgeError(
            "not-configured",
            "Personal Google Keep is not connected. Run Set Up Personal Google Keep POC and connect from Terminal.",
        )

    master_token = keyring.get_password(TOKEN_SERVICE, email)

    if not master_token:
        raise BridgeError(
            "not-configured",
            "The saved Google Keep credential is missing. Reconnect it from the setup command.",
        )

    if not re.fullmatch(r"[0-9a-f]{16}", device_id):
        raise BridgeError(
            "invalid-device-id",
            "The saved device ID is invalid. Disconnect and reconnect the personal Keep proof of concept.",
        )

    return {"email": email, "master_token": master_token, "device_id": device_id}


def normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def updated_at(note: Any) -> Optional[str]:
    timestamps = getattr(note, "timestamps", None)
    value = getattr(timestamps, "updated", None) or getattr(timestamps, "edited", None)
    return value.isoformat() if value and hasattr(value, "isoformat") else None


def is_list(note: Any) -> bool:
    note_type = getattr(note, "type", None)
    return getattr(note_type, "value", note_type) == "LIST"


def score_note(title: str, text: str, query: str) -> Optional[int]:
    normalized_query = normalized_text(query).casefold()
    terms = normalized_query.split()

    if not terms:
        return 0

    normalized_title = normalized_text(title).casefold()
    normalized_body = normalized_text(text).casefold()
    searchable = (normalized_title + " " + normalized_body).strip()

    if any(term not in searchable for term in terms):
        return None

    score = 0
    if normalized_title == normalized_query:
        score += 3000
    elif normalized_title.startswith(normalized_query):
        score += 2000
    elif normalized_query in normalized_title:
        score += 1000
    elif normalized_query in normalized_body:
        score += 400

    for term in terms:
        if normalized_title.startswith(term):
            score += 160
        elif term in normalized_title:
            score += 80
        elif term in normalized_body:
            score += 20

    return score


def note_snippet(text: str, query: str) -> str:
    clean_text = normalized_text(text)
    if not clean_text:
        return "Empty note"

    first_term = next(iter(normalized_text(query).casefold().split()), "")
    match_index = clean_text.casefold().find(first_term) if first_term else 0
    start = max(0, match_index - 60) if match_index > 0 else 0
    end = min(len(clean_text), start + SNIPPET_LENGTH)
    prefix = "…" if start else ""
    suffix = "…" if end < len(clean_text) else ""
    return prefix + clean_text[start:end] + suffix


def note_preview(note: Any, query: str) -> Dict[str, Any]:
    title = str(getattr(note, "title", "") or "Untitled note").strip() or "Untitled note"
    text = str(getattr(note, "text", "") or "")
    return {
        "id": str(getattr(note, "id", "")),
        "title": title,
        "snippet": note_snippet(text, query),
        "isList": is_list(note),
        "updatedAt": updated_at(note),
        "url": getattr(note, "url", None),
    }


def note_detail(note: Any) -> Dict[str, Any]:
    title = str(getattr(note, "title", "") or "Untitled note").strip() or "Untitled note"
    text = str(getattr(note, "text", "") or "")
    truncated = len(text) > MAX_DETAIL_LENGTH
    return {
        "id": str(getattr(note, "id", "")),
        "title": title,
        "text": text[:MAX_DETAIL_LENGTH],
        "truncated": truncated,
        "isList": is_list(note),
        "updatedAt": updated_at(note),
        "url": getattr(note, "url", None),
    }


def default_mirror_directory() -> Path:
    """Returns the visible, Home-scoped folder Raycast indexes by default."""

    return Path.home() / MIRROR_DIRECTORY_NAME


def mirror_manifest_path(directory: Path) -> Path:
    return directory / MIRROR_MANIFEST_FILENAME


def mirror_lock_path(directory: Path) -> Path:
    return directory / MIRROR_LOCK_FILENAME


def is_safe_stage_directory_name(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\.google-keep-search-stage-[0-9a-f]{32}", value) is not None


def stage_directory_path(directory: Path, stage_name: str) -> Path:
    return directory / stage_name


def stage_file_name(entry: Dict[str, str]) -> str:
    return "{}{}".format(entry["noteHash"], MIRROR_STAGE_FILE_SUFFIX)


def is_safe_stage_file_name(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}\.tmp", value) is not None


def is_safe_atomic_temp_file_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"\.google-keep-search-[0-9a-f]{32}\.tmp", value) is not None
    )


def sanitized_text(value: Any) -> str:
    """Makes note-controlled strings safe to encode and render as plain text."""

    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").encode(
        "utf-8", "replace"
    ).decode("utf-8")


def note_hash(note_id: str) -> str:
    return hashlib.sha256(note_id.encode("utf-8", "replace")).hexdigest()


def account_fingerprint(email: str) -> str:
    return hashlib.sha256(normalized_text(email).casefold().encode("utf-8", "replace")).hexdigest()


def mirror_marker(mirror_id: str, note_id_hash: str) -> str:
    return "<!-- google-keep-search-mirror:v{} instance={} note={} -->".format(
        MIRROR_VERSION, mirror_id, note_id_hash
    )


def truncate_utf8(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8", "replace")
    if len(encoded) <= maximum_bytes:
        return encoded.decode("utf-8")

    truncated = encoded[:maximum_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            truncated = truncated[:-1]

    return ""


def mirror_filename_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", normalized_text(sanitized_text(value)))
    cleaned = "".join(
        " " if character in {"/", "\\", ":", "\x00"} or ord(character) < 32 else character
        for character in normalized
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return truncate_utf8(cleaned or "Untitled note", MIRROR_FILENAME_TITLE_BYTES) or "Untitled note"


def mirror_filename(note_id_hash: str, title: str) -> str:
    return "{}{} [{}]{}".format(
        MIRROR_FILE_PREFIX,
        mirror_filename_title(title),
        note_id_hash[:16],
        MIRROR_FILE_SUFFIX,
    )


def is_safe_mirror_filename(value: Any) -> bool:
    match = (
        re.fullmatch(r"Google Keep — .+ \[([0-9a-f]{16})\]\.md", value)
        if isinstance(value, str)
        else None
    )
    return (
        isinstance(value, str)
        and Path(value).name == value
        and value.startswith(MIRROR_FILE_PREFIX)
        and value.endswith(MIRROR_FILE_SUFFIX)
        and len(value.encode("utf-8", "replace")) <= 240
        and match is not None
    )


def is_hex(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def is_private_regular_file(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and metadata.st_nlink == 1
        and not metadata.st_mode & 0o077
    )


def validate_mirror_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
    except FileNotFoundError as error:
        raise BridgeError(
            "mirror-directory-unavailable",
            "The local Google Keep Search mirror folder is unavailable.",
        ) from error

    if (
        directory.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise BridgeError(
            "mirror-directory-unsafe",
            "The Google Keep Search mirror folder must be a private folder owned by the current macOS user.",
        )


def ensure_mirror_directory() -> Path:
    directory = default_mirror_directory()

    try:
        if not directory.exists() and not directory.is_symlink():
            directory.mkdir(mode=0o700)
        elif directory.is_symlink() or not directory.is_dir():
            raise BridgeError(
                "mirror-directory-unsafe",
                "The Google Keep Search mirror path exists but is not a private folder. Rename it before syncing.",
            )

        os.chmod(directory, 0o700)
        validate_mirror_directory(directory)

        manifest = mirror_manifest_path(directory)
        lock = mirror_lock_path(directory)
        if manifest.is_symlink() or lock.is_symlink():
            raise BridgeError(
                "mirror-directory-unsafe",
                "The Google Keep Search mirror folder contains an unsafe symbolic link.",
            )
        if not manifest.exists():
            allowed_paths = {".DS_Store", MIRROR_LOCK_FILENAME}
            unexpected_paths = [
                path
                for path in directory.iterdir()
                if (
                    path.name not in allowed_paths
                    and not is_safe_stage_directory_name(path.name)
                    and not is_safe_atomic_temp_file_name(path.name)
                )
            ]
            if unexpected_paths:
                raise BridgeError(
                    "mirror-directory-not-empty",
                    "The Google Keep Search mirror folder contains files not created by this extension. "
                    "Move them elsewhere before syncing.",
                )

    except BridgeError:
        raise
    except OSError as error:
        raise BridgeError(
            "mirror-directory-unavailable",
            "The local Google Keep Search mirror folder could not be prepared.",
        ) from error

    return directory


@contextmanager
def mirror_lock(directory: Path) -> Iterable[None]:
    path = mirror_lock_path(directory)
    if path.is_symlink():
        raise BridgeError("mirror-lock-unsafe", "The local Google Keep Search mirror lock is unsafe.")

    descriptor = None
    try:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise BridgeError("mirror-lock-unsafe", "The local Google Keep Search mirror lock is unsafe.")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BridgeError(
                "mirror-busy",
                "Another Google Keep Root Search sync is already running. Wait for it to finish and retry.",
            ) from error
        yield
    except BridgeError:
        raise
    except OSError as error:
        raise BridgeError("mirror-lock-failed", "The local Google Keep Search mirror could not be locked.") from error
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_mirror_entry(entry: Any) -> Dict[str, str]:
    if not isinstance(entry, dict) or set(entry) != {"noteHash", "filename", "contentHash"}:
        raise BridgeError("mirror-manifest-invalid", "The local Google Keep Search mirror manifest has an invalid file entry.")

    note_id_hash = entry.get("noteHash")
    filename = entry.get("filename")
    content_hash = entry.get("contentHash")
    filename_match = re.fullmatch(
        r"Google Keep — .+ \[([0-9a-f]{16})\]\.md",
        filename if isinstance(filename, str) else "",
    )
    if (
        not is_hex(note_id_hash, 64)
        or not is_safe_mirror_filename(filename)
        or not is_hex(content_hash, 64)
        or filename_match is None
        or filename_match.group(1) != note_id_hash[:16]
    ):
        raise BridgeError("mirror-manifest-invalid", "The local Google Keep Search mirror manifest has an unsafe file entry.")

    return {"noteHash": note_id_hash, "filename": filename, "contentHash": content_hash}


def validate_unique_entries(entries: Iterable[Dict[str, str]], description: str, maximum_entries: int) -> None:
    note_hashes = set()
    filenames = set()
    count = 0
    for entry in entries:
        count += 1
        if count > maximum_entries:
            raise BridgeError("mirror-manifest-invalid", "The local Google Keep Search mirror manifest has too many file entries.")
        if entry["noteHash"] in note_hashes or entry["filename"] in filenames:
            raise BridgeError("mirror-manifest-invalid", description)
        note_hashes.add(entry["noteHash"])
        filenames.add(entry["filename"])


def validate_pending_write(value: Any, existing_entries: Iterable[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    if value is None:
        return None

    if (
        not isinstance(value, dict)
        or set(value) != {"stage", "entries"}
        or not is_safe_stage_directory_name(value.get("stage"))
        or not isinstance(value.get("entries"), list)
    ):
        raise BridgeError(
            "mirror-manifest-invalid",
            "The local Google Keep Search mirror manifest has an invalid pending write transaction.",
        )

    entries = [validate_mirror_entry(entry) for entry in value["entries"]]
    validate_unique_entries(
        entries,
        "The local Google Keep Search mirror transaction contains duplicate file entries.",
        MIRROR_NOTE_LIMIT,
    )
    existing_by_hash = {entry["noteHash"]: entry for entry in existing_entries}
    existing_by_filename = {entry["filename"]: entry for entry in existing_entries}

    for entry in entries:
        previous_by_hash = existing_by_hash.get(entry["noteHash"])
        previous_by_filename = existing_by_filename.get(entry["filename"])
        if (
            (previous_by_hash is not None and previous_by_hash["filename"] != entry["filename"])
            or (previous_by_filename is not None and previous_by_filename["noteHash"] != entry["noteHash"])
        ):
            raise BridgeError(
                "mirror-manifest-invalid",
                "The local Google Keep Search mirror transaction has an unsafe filename change.",
            )

    return {"stage": value["stage"], "entries": entries}


def read_mirror_manifest(directory: Path) -> Optional[Dict[str, Any]]:
    manifest_path = mirror_manifest_path(directory)
    try:
        manifest_bytes = read_private_file_bytes(manifest_path, MIRROR_MANIFEST_BYTES_LIMIT)
    except BridgeError as error:
        raise BridgeError(
            "mirror-manifest-unsafe",
            "The local Google Keep Search mirror manifest is not a private regular file. Remove the mirror folder safely and retry.",
        ) from error

    if manifest_bytes is None:
        return None

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise BridgeError(
            "mirror-manifest-invalid",
            "The local Google Keep Search mirror manifest could not be read. Remove the mirror safely and sync again.",
        ) from error

    required_keys = {
        "kind",
        "version",
        "mirrorId",
        "accountFingerprint",
        "entries",
        "pendingDeletion",
    }
    allowed_keys = required_keys | {"pendingWrite"}
    if (
        not isinstance(manifest, dict)
        or (set(manifest) != required_keys and set(manifest) != allowed_keys)
        or manifest.get("kind") != MIRROR_MANIFEST_KIND
        or manifest.get("version") != MIRROR_VERSION
        or not is_hex(manifest.get("mirrorId"), 32)
        or not is_hex(manifest.get("accountFingerprint"), 64)
        or not isinstance(manifest.get("entries"), list)
        or not isinstance(manifest.get("pendingDeletion"), list)
    ):
        raise BridgeError(
            "mirror-manifest-invalid",
            "The local Google Keep Search mirror manifest uses an unsupported format. Remove the mirror safely and sync again.",
        )

    entries = [validate_mirror_entry(entry) for entry in manifest["entries"]]
    pending_deletion = [validate_mirror_entry(entry) for entry in manifest["pendingDeletion"]]
    existing_entries = entries + pending_deletion
    validate_unique_entries(
        existing_entries,
        "The local Google Keep Search mirror manifest contains duplicate file entries. Remove the mirror safely and sync again.",
        MIRROR_NOTE_LIMIT * 2,
    )
    pending_write = validate_pending_write(manifest.get("pendingWrite"), existing_entries)

    return {
        "kind": MIRROR_MANIFEST_KIND,
        "version": MIRROR_VERSION,
        "mirrorId": manifest["mirrorId"],
        "accountFingerprint": manifest["accountFingerprint"],
        "entries": entries,
        "pendingDeletion": pending_deletion,
        "pendingWrite": pending_write,
    }


def new_mirror_manifest(email: str) -> Dict[str, Any]:
    return {
        "kind": MIRROR_MANIFEST_KIND,
        "version": MIRROR_VERSION,
        "mirrorId": secrets.token_hex(16),
        "accountFingerprint": account_fingerprint(email),
        "entries": [],
        "pendingDeletion": [],
        "pendingWrite": None,
    }


def atomic_write_text(path: Path, content: str) -> None:
    temporary_path = None
    descriptor = None

    try:
        temporary_path = path.parent / "{}{}.tmp".format(MIRROR_ATOMIC_TEMP_FILE_PREFIX, secrets.token_hex(16))
        descriptor = os.open(
            temporary_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        temporary_file = os.fdopen(descriptor, "wb")
        descriptor = None
        with temporary_file:
            temporary_file.write(content.encode("utf-8"))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        fsync_directory(path.parent)
    except OSError as error:
        raise BridgeError(
            "mirror-write-failed",
            "The local Google Keep Search mirror could not be written securely.",
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def fsync_directory(directory: Path) -> None:
    """Best-effort directory sync after an atomic rename on macOS."""

    descriptor = None
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        # Some filesystems do not permit syncing a directory. The file itself
        # was already synced before the rename, so keep the operation usable.
        pass
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def cleanup_orphan_atomic_temp_files(directory: Path) -> None:
    try:
        temporary_files = [path for path in directory.iterdir() if is_safe_atomic_temp_file_name(path.name)]
    except OSError as error:
        raise BridgeError("mirror-directory-unavailable", "The local Google Keep Search mirror folder could not be read.") from error

    for temporary_file in temporary_files:
        if not is_private_regular_file(temporary_file):
            raise BridgeError("mirror-file-conflict", "A local Google Keep mirror temporary file is unsafe and was preserved.")

    try:
        for temporary_file in temporary_files:
            temporary_file.unlink()
        if temporary_files:
            fsync_directory(directory)
    except OSError as error:
        raise BridgeError("mirror-remove-failed", "A local Google Keep mirror temporary file could not be removed safely.") from error


def read_private_file_bytes(path: Path, maximum_bytes: int) -> Optional[bytes]:
    """Reads an owned, private regular file without following a symlink."""

    if path.is_symlink():
        raise BridgeError("mirror-file-conflict", "A local Google Keep mirror file is unsafe and was not changed.")

    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as error:
        raise BridgeError("mirror-file-unreadable", "A local Google Keep mirror file could not be verified safely.") from error

    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
        ):
            raise BridgeError("mirror-file-conflict", "A local Google Keep mirror file is unsafe and was not changed.")
        if metadata.st_size > maximum_bytes:
            raise BridgeError("mirror-file-unreadable", "A local Google Keep mirror file could not be verified safely.")

        chunks = []
        remaining = maximum_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)

        content = b"".join(chunks)
        if len(content) > maximum_bytes:
            raise BridgeError("mirror-file-unreadable", "A local Google Keep mirror file could not be verified safely.")
        return content
    except BridgeError:
        raise
    except OSError as error:
        raise BridgeError("mirror-file-unreadable", "A local Google Keep mirror file could not be verified safely.") from error
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def entry_content_matches(content: bytes, manifest: Dict[str, Any], entry: Dict[str, str]) -> bool:
    expected_marker = (mirror_marker(manifest["mirrorId"], entry["noteHash"]) + "\n").encode("utf-8")
    return content.startswith(expected_marker) and hashlib.sha256(content).hexdigest() == entry["contentHash"]


def text_fence(value: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"~+", value)), default=0)
    return "~" * max(3, longest_run + 1)


def mirror_note_content(note: Any, mirror_id: str, note_id_hash: str) -> str:
    title = normalized_text(sanitized_text(getattr(note, "title", ""))) or "Untitled note"
    text = sanitized_text(getattr(note, "text", "")).rstrip()
    metadata = ["Title: {}".format(title)]
    updated = updated_at(note)

    if updated:
        metadata.append("Updated: {}".format(updated))
    if is_list(note):
        metadata.append("Type: checklist")

    payload = "\n".join(metadata + ["", text])
    fence = text_fence(payload)
    return "\n".join(
        [
            mirror_marker(mirror_id, note_id_hash),
            "# Google Keep mirror",
            "",
            "This local file is an opt-in, read-only Google Keep mirror for Raycast Root Search.",
            "",
            "{}text".format(fence),
            payload,
            fence,
            "",
        ]
    )


def read_and_validate_entry_file(directory: Path, manifest: Dict[str, Any], entry: Dict[str, str]) -> Optional[bytes]:
    path = directory / entry["filename"]
    content = read_private_file_bytes(path, MIRROR_FILE_BYTES_LIMIT)
    if content is None:
        return None

    if not entry_content_matches(content, manifest, entry):
        raise BridgeError(
            "mirror-file-conflict",
            "A local Google Keep mirror file was changed outside this extension and was preserved.",
        )

    return content


def preflight_mirror_files(directory: Path, manifest: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    entries_by_filename = {}
    for entry in manifest["entries"] + manifest["pendingDeletion"]:
        read_and_validate_entry_file(directory, manifest, entry)
        entries_by_filename[entry["filename"]] = entry
    return entries_by_filename


def write_mirror_manifest(directory: Path, manifest: Dict[str, Any]) -> None:
    content = json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    atomic_write_text(mirror_manifest_path(directory), content)


def existing_entries_by_hash(manifest: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    return {entry["noteHash"]: entry for entry in manifest["entries"] + manifest["pendingDeletion"]}


def build_mirror_snapshot(notes: Iterable[Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
    previous_entries = existing_entries_by_hash(manifest)
    snapshots = []
    note_hashes = set()
    filenames = set()
    total_bytes = 0

    for note in notes:
        if len(snapshots) >= MIRROR_NOTE_LIMIT:
            raise BridgeError("mirror-too-large", "Google Keep returned too many notes for the local Root Search mirror.")

        note_id = sanitized_text(getattr(note, "id", "")).strip()
        if not note_id:
            raise BridgeError("mirror-note-invalid", "Google Keep returned a note without a stable identifier.")
        note_id_hash = note_hash(note_id)
        if note_id_hash in note_hashes:
            raise BridgeError("mirror-note-invalid", "Google Keep returned duplicate note identifiers during mirror sync.")

        body = sanitized_text(getattr(note, "text", ""))
        if len(body.encode("utf-8")) > MIRROR_NOTE_BYTES_LIMIT:
            raise BridgeError("mirror-too-large", "A Google Keep note is too large for the local Root Search mirror.")

        previous_entry = previous_entries.get(note_id_hash)
        title = sanitized_text(getattr(note, "title", "")) or "Untitled note"
        filename = previous_entry["filename"] if previous_entry else mirror_filename(note_id_hash, title)
        if filename in filenames:
            raise BridgeError("mirror-file-conflict", "Google Keep mirror filenames collided. Retry the sync.")

        content = mirror_note_content(note, manifest["mirrorId"], note_id_hash)
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MIRROR_FILE_BYTES_LIMIT:
            raise BridgeError("mirror-too-large", "A Google Keep note is too large for the local Root Search mirror.")
        total_bytes += len(content_bytes)
        if total_bytes > MIRROR_TOTAL_BYTES_LIMIT:
            raise BridgeError("mirror-too-large", "Google Keep notes exceed the local Root Search mirror size limit.")
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        snapshots.append(
            {
                "entry": {"noteHash": note_id_hash, "filename": filename, "contentHash": content_hash},
                "content": content,
            }
        )
        note_hashes.add(note_id_hash)
        filenames.add(filename)

    return {"snapshots": snapshots, "totalBytes": total_bytes}


def remove_entry_file(directory: Path, manifest: Dict[str, Any], entry: Dict[str, str]) -> bool:
    path = directory / entry["filename"]
    content = read_private_file_bytes(path, MIRROR_FILE_BYTES_LIMIT)
    if content is None:
        return False
    if not entry_content_matches(content, manifest, entry):
        raise BridgeError(
            "mirror-file-conflict",
            "A local Google Keep mirror file was changed outside this extension and was preserved.",
        )
    try:
        path.unlink()
        fsync_directory(directory)
        return True
    except OSError as error:
        raise BridgeError("mirror-remove-failed", "A local Google Keep mirror file could not be removed safely.") from error


def mirror_result(directory: Path, notes: int, written: int, removed: int) -> Dict[str, Any]:
    return {
        "directory": str(directory),
        "notes": notes,
        "written": written,
        "removed": removed,
        "unchanged": max(notes - written, 0),
    }


def validate_stage_directory(directory: Path, stage_name: str, allow_missing: bool = False) -> Optional[Path]:
    if not is_safe_stage_directory_name(stage_name):
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory is unsafe.")

    path = stage_directory_path(directory, stage_name)
    if path.is_symlink():
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory is unsafe.")
    if not path.exists():
        if allow_missing:
            return None
        raise BridgeError("mirror-stage-missing", "The local Google Keep mirror staging data is missing. Remove the mirror safely and retry.")

    try:
        metadata = path.lstat()
    except OSError as error:
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory is unsafe.") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory is unsafe.")

    return path


def validate_stage_contents(stage: Path, manifest: Dict[str, Any], entries: Iterable[Dict[str, str]]) -> None:
    cleanup_orphan_atomic_temp_files(stage)
    expected_entries = {stage_file_name(entry): entry for entry in entries}
    try:
        children = list(stage.iterdir())
    except OSError as error:
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory could not be verified.") from error

    for child in children:
        entry = expected_entries.get(child.name)
        if entry is None or not is_safe_stage_file_name(child.name):
            raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory has unexpected content.")
        content = read_private_file_bytes(child, MIRROR_FILE_BYTES_LIMIT)
        if content is None or not entry_content_matches(content, manifest, entry):
            raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging data is invalid.")


def remove_stage_directory(directory: Path, stage_name: str, manifest: Dict[str, Any], entries: Iterable[Dict[str, str]]) -> None:
    stage = validate_stage_directory(directory, stage_name, allow_missing=True)
    if stage is None:
        return

    validate_stage_contents(stage, manifest, entries)
    try:
        for child in stage.iterdir():
            child.unlink()
        stage.rmdir()
        fsync_directory(directory)
    except OSError as error:
        raise BridgeError("mirror-remove-failed", "The local Google Keep mirror staging data could not be removed safely.") from error


def remove_orphan_stage_directory(directory: Path, stage: Path) -> None:
    stage_path = validate_stage_directory(directory, stage.name)
    if stage_path is None:
        return
    cleanup_orphan_atomic_temp_files(stage_path)
    try:
        children = list(stage_path.iterdir())
    except OSError as error:
        raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory could not be verified.") from error

    for child in children:
        if not is_safe_stage_file_name(child.name):
            raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory has unexpected content.")
        content = read_private_file_bytes(child, MIRROR_FILE_BYTES_LIMIT)
        if content is None or not content.startswith(b"<!-- google-keep-search-mirror:v"):
            raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging directory has unexpected content.")

    try:
        for child in children:
            child.unlink()
        stage_path.rmdir()
        fsync_directory(directory)
    except OSError as error:
        raise BridgeError("mirror-remove-failed", "The local Google Keep mirror staging data could not be removed safely.") from error


def cleanup_orphan_stages(directory: Path, active_stage_name: Optional[str] = None) -> None:
    try:
        stages = [path for path in directory.iterdir() if is_safe_stage_directory_name(path.name)]
    except OSError as error:
        raise BridgeError("mirror-directory-unavailable", "The local Google Keep Search mirror folder could not be read.") from error

    for stage in stages:
        if stage.name != active_stage_name:
            remove_orphan_stage_directory(directory, stage)


def has_only_mirror_housekeeping_files(directory: Path) -> bool:
    try:
        return all(path.name in {".DS_Store", MIRROR_LOCK_FILENAME} for path in directory.iterdir())
    except OSError as error:
        raise BridgeError("mirror-directory-unavailable", "The local Google Keep Search mirror folder could not be read.") from error


def create_stage_directory(directory: Path, manifest: Dict[str, Any], snapshots: Iterable[Dict[str, Any]]) -> str:
    stage_name = "{}{}".format(MIRROR_STAGE_DIRECTORY_PREFIX, secrets.token_hex(16))
    stage = stage_directory_path(directory, stage_name)
    try:
        stage.mkdir(mode=0o700)
        os.chmod(stage, 0o700)
        validate_stage_directory(directory, stage_name)
    except BridgeError:
        raise
    except OSError as error:
        raise BridgeError("mirror-write-failed", "The local Google Keep mirror staging directory could not be created.") from error

    entries = []
    try:
        for snapshot in snapshots:
            entry = snapshot["entry"]
            entries.append(entry)
            atomic_write_text(stage / stage_file_name(entry), snapshot["content"])
        fsync_directory(stage)
        return stage_name
    except Exception:
        try:
            remove_stage_directory(directory, stage_name, manifest, entries)
        except BridgeError:
            pass
        raise


def target_write_state(
    directory: Path,
    manifest: Dict[str, Any],
    entry: Dict[str, str],
    previous_by_filename: Dict[str, Dict[str, str]],
) -> str:
    content = read_private_file_bytes(directory / entry["filename"], MIRROR_FILE_BYTES_LIMIT)
    if content is None:
        return "missing"
    if entry_content_matches(content, manifest, entry):
        return "desired"

    previous = previous_by_filename.get(entry["filename"])
    if previous is not None and entry_content_matches(content, manifest, previous):
        return "previous"

    raise BridgeError("mirror-file-conflict", "A local file conflicts with a Google Keep mirror filename.")


def replace_staged_file(stage_file: Path, target_file: Path) -> None:
    try:
        os.replace(stage_file, target_file)
        fsync_directory(target_file.parent)
    except OSError as error:
        raise BridgeError("mirror-write-failed", "The local Google Keep mirror file could not be written securely.") from error


def stale_entries_for(desired_entries: Iterable[Dict[str, str]], manifest: Dict[str, Any]) -> list[Dict[str, str]]:
    desired_hashes = {entry["noteHash"] for entry in desired_entries}
    return [
        entry
        for entry in manifest["entries"] + manifest["pendingDeletion"]
        if entry["noteHash"] not in desired_hashes
    ]


def finish_pending_write(directory: Path, manifest: Dict[str, Any]) -> tuple[Dict[str, Any], int, int]:
    pending_write = manifest["pendingWrite"]
    if pending_write is None:
        return manifest, 0, 0

    desired_entries = pending_write["entries"]
    previous_entries = manifest["entries"] + manifest["pendingDeletion"]
    previous_by_filename = {entry["filename"]: entry for entry in previous_entries}
    stale_entries = stale_entries_for(desired_entries, manifest)
    for entry in stale_entries:
        read_and_validate_entry_file(directory, manifest, entry)

    stage = validate_stage_directory(directory, pending_write["stage"], allow_missing=True)
    if stage is not None:
        validate_stage_contents(stage, manifest, desired_entries)

    written = 0
    for entry in desired_entries:
        state = target_write_state(directory, manifest, entry, previous_by_filename)
        stage_file = stage / stage_file_name(entry) if stage is not None else None
        staged_content = read_private_file_bytes(stage_file, MIRROR_FILE_BYTES_LIMIT) if stage_file is not None else None

        if staged_content is not None and not entry_content_matches(staged_content, manifest, entry):
            raise BridgeError("mirror-stage-unsafe", "The local Google Keep mirror staging data is invalid.")
        if state == "desired":
            continue
        if staged_content is None:
            raise BridgeError(
                "mirror-stage-missing",
                "The local Google Keep mirror staging data is incomplete. Remove the mirror safely and retry.",
            )

        replace_staged_file(stage_file, directory / entry["filename"])
        written += 1

    for entry in desired_entries:
        read_and_validate_entry_file(directory, manifest, entry)

    remove_stage_directory(directory, pending_write["stage"], manifest, desired_entries)
    pending_manifest = {
        **manifest,
        "entries": desired_entries,
        "pendingDeletion": stale_entries,
        "pendingWrite": None,
    }
    write_mirror_manifest(directory, pending_manifest)

    removed = 0
    for entry in stale_entries:
        if remove_entry_file(directory, pending_manifest, entry):
            removed += 1

    final_manifest = {**pending_manifest, "pendingDeletion": []}
    write_mirror_manifest(directory, final_manifest)
    return final_manifest, written, removed


def sync_notes_to_mirror(notes: Iterable[Any], directory: Path, email: str) -> Dict[str, Any]:
    validate_mirror_directory(directory)
    with mirror_lock(directory):
        manifest = read_mirror_manifest(directory)
        cleanup_orphan_atomic_temp_files(directory)
        if manifest is None:
            manifest = new_mirror_manifest(email)
        elif manifest["accountFingerprint"] != account_fingerprint(email):
            raise BridgeError(
                "mirror-account-mismatch",
                "This local Root Search mirror belongs to a different Google account. Remove it before switching accounts.",
            )

        active_stage_name = manifest["pendingWrite"]["stage"] if manifest["pendingWrite"] else None
        cleanup_orphan_stages(directory, active_stage_name)
        if manifest["pendingWrite"]:
            manifest, _, _ = finish_pending_write(directory, manifest)
            cleanup_orphan_stages(directory)

        snapshot = build_mirror_snapshot(notes, manifest)
        desired_entries = [item["entry"] for item in snapshot["snapshots"]]
        if manifest["entries"] and not desired_entries:
            raise BridgeError(
                "mirror-empty-sync",
                "Google Keep returned no visible notes, so the existing Root Search mirror was preserved. Retry later or remove it explicitly.",
            )

        preflight_mirror_files(directory, manifest)
        previous_by_filename = {
            entry["filename"]: entry for entry in manifest["entries"] + manifest["pendingDeletion"]
        }
        written = sum(
            target_write_state(directory, manifest, entry, previous_by_filename) != "desired"
            for entry in desired_entries
        )
        stale_entries = stale_entries_for(desired_entries, manifest)
        if not written and not stale_entries:
            return mirror_result(directory, len(desired_entries), 0, 0)

        stage_name = create_stage_directory(directory, manifest, snapshot["snapshots"])
        transaction_manifest = {
            **manifest,
            "pendingWrite": {"stage": stage_name, "entries": desired_entries},
        }
        write_mirror_manifest(directory, transaction_manifest)
        _, transaction_written, removed = finish_pending_write(directory, transaction_manifest)
        return mirror_result(directory, len(desired_entries), max(written, transaction_written), removed)


def clear_mirror() -> Dict[str, Any]:
    directory = default_mirror_directory()
    if directory.is_symlink():
        raise BridgeError("mirror-directory-unsafe", "The Google Keep Search mirror folder is an unsafe symbolic link.")
    if not directory.exists():
        return mirror_result(directory, 0, 0, 0)

    validate_mirror_directory(directory)
    with mirror_lock(directory):
        manifest = read_mirror_manifest(directory)
        cleanup_orphan_atomic_temp_files(directory)
        if manifest is None:
            cleanup_orphan_stages(directory)
            if has_only_mirror_housekeeping_files(directory):
                return mirror_result(directory, 0, 0, 0)
            raise BridgeError(
                "mirror-not-initialized",
                "The Google Keep Search mirror folder was not created by this extension and was not removed.",
            )

        active_stage_name = manifest["pendingWrite"]["stage"] if manifest["pendingWrite"] else None
        cleanup_orphan_stages(directory, active_stage_name)
        candidates_by_filename: Dict[str, list[Dict[str, str]]] = {}
        for entry in manifest["entries"] + manifest["pendingDeletion"]:
            candidates_by_filename.setdefault(entry["filename"], [])
            if entry not in candidates_by_filename[entry["filename"]]:
                candidates_by_filename[entry["filename"]].append(entry)
        if manifest["pendingWrite"]:
            for entry in manifest["pendingWrite"]["entries"]:
                candidates_by_filename.setdefault(entry["filename"], [])
                if entry not in candidates_by_filename[entry["filename"]]:
                    candidates_by_filename[entry["filename"]].append(entry)

        selected_entries = []
        for filename, candidates in candidates_by_filename.items():
            content = read_private_file_bytes(directory / filename, MIRROR_FILE_BYTES_LIMIT)
            if content is None:
                continue
            matching_entries = [entry for entry in candidates if entry_content_matches(content, manifest, entry)]
            if len(matching_entries) != 1:
                raise BridgeError(
                    "mirror-file-conflict",
                    "A local Google Keep mirror file was changed outside this extension and was preserved.",
                )
            selected_entries.append(matching_entries[0])

        pending_manifest = {
            **manifest,
            "entries": [],
            "pendingDeletion": selected_entries,
            "pendingWrite": None,
        }
        write_mirror_manifest(directory, pending_manifest)
        if active_stage_name and manifest["pendingWrite"]:
            remove_stage_directory(directory, active_stage_name, manifest, manifest["pendingWrite"]["entries"])

        removed = 0
        for entry in selected_entries:
            if remove_entry_file(directory, pending_manifest, entry):
                removed += 1

        manifest_path = mirror_manifest_path(directory)
        if not is_private_regular_file(manifest_path):
            raise BridgeError("mirror-manifest-unsafe", "The local Google Keep mirror manifest was not removed safely.")
        try:
            manifest_path.unlink()
            fsync_directory(directory)
        except OSError as error:
            raise BridgeError("mirror-remove-failed", "The local Google Keep mirror could not be removed safely.") from error

    return mirror_result(directory, 0, 0, removed)


def read_request() -> Dict[str, Any]:
    raw_request = sys.stdin.read()

    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError as error:
        raise BridgeError("invalid-request", "The local Raycast request could not be read.") from error

    if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
        raise BridgeError("invalid-request", "The local Raycast request uses an unsupported protocol version.")

    return request


def load_keep(credentials: Optional[Dict[str, str]] = None) -> Any:
    require_supported_python()
    dependencies = dependency_status()

    if not dependencies["gkeepapi"] or not dependencies["keyring"]:
        raise BridgeError("dependencies-missing", "Install the pinned personal Keep companion dependencies first.")

    credentials = credentials or active_credentials()

    try:
        import gkeepapi  # pylint: disable=import-outside-toplevel

        logging.getLogger("gkeepapi").setLevel(logging.CRITICAL)
        logging.getLogger("requests").setLevel(logging.CRITICAL)
        keep = gkeepapi.Keep()
        keep.authenticate(credentials["email"], credentials["master_token"], device_id=credentials["device_id"])
        return keep
    except BridgeError:
        raise
    except Exception as error:
        raise BridgeError(
            "authentication-failed",
            "Google rejected the saved master token or device ID, or the private Keep sync failed. "
            "Disconnect and reconnect the proof of concept before trying again.",
        ) from error


def visible_notes(keep: Any) -> Iterable[Any]:
    return (
        note
        for note in keep.all()
        if not getattr(note, "trashed", False) and not getattr(note, "deleted", False)
    )


def search() -> int:
    request = read_request()
    query = str(request.get("query", ""))[:MAX_QUERY_LENGTH]
    keep = load_keep()
    matching_notes = []

    for note in visible_notes(keep):
        title = str(getattr(note, "title", "") or "")
        text = str(getattr(note, "text", "") or "")
        score = score_note(title, text, query)

        if score is None:
            continue

        matching_notes.append((score, updated_at(note) or "", note_preview(note, query)))

    matching_notes.sort(key=lambda item: (item[0], item[1], item[2]["title"].casefold()), reverse=True)
    emit({"ok": True, "notes": [item[2] for item in matching_notes[:MAX_RESULTS]]})
    return 0


def get_note() -> int:
    request = read_request()
    requested_id = str(request.get("id", ""))[:500]

    if not requested_id:
        raise BridgeError("invalid-request", "The selected note ID is missing.")

    keep = load_keep()

    for note in visible_notes(keep):
        if str(getattr(note, "id", "")) == requested_id:
            emit({"ok": True, "note": note_detail(note)})
            return 0

    raise BridgeError("note-not-found", "The selected note is no longer available. Refresh the search and try again.")


def sync_mirror() -> int:
    read_request()
    credentials = active_credentials()
    keep = load_keep(credentials)
    result = sync_notes_to_mirror(visible_notes(keep), ensure_mirror_directory(), credentials["email"])
    emit({"ok": True, "mirror": result})
    return 0


def clear_mirror_command() -> int:
    read_request()
    emit({"ok": True, "mirror": clear_mirror()})
    return 0


def ensure_mirror_account_compatible(email: str) -> None:
    directory = default_mirror_directory()
    if directory.is_symlink():
        raise BridgeError(
            "mirror-directory-unsafe",
            "The Google Keep Search mirror folder is an unsafe symbolic link. Remove it before connecting an account.",
        )
    if not directory.exists():
        return

    validate_mirror_directory(directory)
    with mirror_lock(directory):
        manifest = read_mirror_manifest(directory)
        if manifest and manifest["accountFingerprint"] != account_fingerprint(email):
            raise BridgeError(
                "mirror-account-mismatch",
                "This local Root Search mirror belongs to a different Google account. Remove it before connecting another account.",
            )


def prompt(message: str) -> str:
    print(message, file=sys.stderr, end="", flush=True)
    return input()


def connect() -> int:
    require_supported_python()
    dependencies = dependency_status()

    if not dependencies["gkeepapi"] or not dependencies["keyring"]:
        raise BridgeError("dependencies-missing", "Install the pinned personal Keep companion dependencies first.")

    if not sys.stdin.isatty():
        raise BridgeError(
            "interactive-terminal-required",
            "Connect this proof of concept from a Terminal window so the master token is entered through a hidden prompt.",
        )

    keyring = require_keyring()
    print("\nEXPERIMENTAL PERSONAL GOOGLE KEEP POC", file=sys.stderr)
    print("This uses an unsupported private Google Keep API.", file=sys.stderr)
    print("The master token has broad Google-account access and is not a read-only OAuth scope.", file=sys.stderr)
    print("It will be stored only in your macOS Keychain. Do not enter your Google password or MFA code.\n", file=sys.stderr)

    acknowledgement = prompt("Type I UNDERSTAND to continue: ").strip()
    if acknowledgement != "I UNDERSTAND":
        raise BridgeError("cancelled", "Connection cancelled without saving a credential.")

    email = prompt("Google account email: ").strip()
    if not email or "@" not in email:
        raise BridgeError("invalid-email", "Enter a valid Google account email address.")

    ensure_mirror_account_compatible(email)

    master_token = getpass.getpass("gkeepapi master token (input hidden): ").strip()
    if not master_token:
        raise BridgeError("missing-token", "No master token was entered.")

    existing_email = keyring.get_password(ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)
    device_id = keyring.get_password(DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME) or secrets.token_hex(8)

    try:
        keyring.set_password(TOKEN_SERVICE, email, master_token)
        keyring.set_password(DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME, device_id)
        keyring.set_password(ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME, email)
    except Exception as error:
        try:
            delete_password(keyring, TOKEN_SERVICE, email)
            delete_password(keyring, DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME)
            delete_password(keyring, ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)
        except Exception:
            pass
        raise BridgeError("keychain-write-failed", "macOS Keychain rejected the credential. Nothing was kept by the POC.") from error

    if existing_email and existing_email != email:
        delete_password(keyring, TOKEN_SERVICE, existing_email)

    emit({"ok": True, "connected": True})
    return 0


def disconnect() -> int:
    require_supported_python()
    keyring = require_keyring()
    email = keyring.get_password(ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)

    if email:
        delete_password(keyring, TOKEN_SERVICE, email)

    delete_password(keyring, ACTIVE_ACCOUNT_SERVICE, ACTIVE_ACCOUNT_NAME)
    delete_password(keyring, DEVICE_ID_SERVICE, ACTIVE_ACCOUNT_NAME)
    emit({"ok": True, "disconnected": True})
    return 0


def status() -> int:
    dependencies = dependency_status()
    keychain = keychain_status()
    emit(
        {
            "ok": True,
            "status": {
                "pythonVersion": python_version(),
                "supportedPython": supported_python(),
                "dependencies": dependencies,
                "keychainAvailable": keychain["available"],
                "configured": keychain["configured"],
            },
        }
    )
    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local personal Google Keep Raycast POC bridge")
    subcommands = parser.add_subparsers(dest="operation", required=True)

    for operation in ("status", "connect", "disconnect", "search", "get", "sync-mirror", "clear-mirror"):
        subcommands.add_parser(operation)

    return parser.parse_args()


def main() -> int:
    operation = parse_arguments().operation

    try:
        if operation == "status":
            return status()
        if operation == "connect":
            return connect()
        if operation == "disconnect":
            return disconnect()
        if operation == "search":
            return search()
        if operation == "get":
            return get_note()
        if operation == "sync-mirror":
            return sync_mirror()
        if operation == "clear-mirror":
            return clear_mirror_command()
        return fail("invalid-operation", "The local Raycast operation is not supported.")
    except BridgeError as error:
        return fail(error.code, error.message)
    except Exception:
        return fail("unexpected-error", "The local personal Keep companion stopped unexpectedly. Reconnect it and try again.")


if __name__ == "__main__":
    raise SystemExit(main())
