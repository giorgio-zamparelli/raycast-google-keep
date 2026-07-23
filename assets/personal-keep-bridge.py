#!/usr/bin/env python3
"""Local-only bridge for the experimental personal Google Keep Raycast command.

This deliberately talks only to gkeepapi. It never receives a Google password,
does not persist note content, and emits structured JSON without tracebacks.
"""

from __future__ import annotations

import argparse
import getpass
import importlib.util
import json
import logging
import platform
import re
import secrets
import sys
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


def read_request() -> Dict[str, Any]:
    raw_request = sys.stdin.read()

    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError as error:
        raise BridgeError("invalid-request", "The local Raycast request could not be read.") from error

    if not isinstance(request, dict) or request.get("version") != PROTOCOL_VERSION:
        raise BridgeError("invalid-request", "The local Raycast request uses an unsupported protocol version.")

    return request


def load_keep() -> Any:
    require_supported_python()
    dependencies = dependency_status()

    if not dependencies["gkeepapi"] or not dependencies["keyring"]:
        raise BridgeError("dependencies-missing", "Install the pinned personal Keep companion dependencies first.")

    credentials = active_credentials()

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

    for operation in ("status", "connect", "disconnect", "search", "get"):
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
        return fail("invalid-operation", "The local Raycast operation is not supported.")
    except BridgeError as error:
        return fail(error.code, error.message)
    except Exception:
        return fail("unexpected-error", "The local personal Keep companion stopped unexpectedly. Reconnect it and try again.")


if __name__ == "__main__":
    raise SystemExit(main())
