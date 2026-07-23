# Changelog

## Unreleased

- Added an opt-in, local-only experimental personal Gmail Google Keep proof of concept.
- Added a macOS Keychain-backed Python bridge built on `gkeepapi`; it never accepts passwords, MFA codes, browser cookies, or master tokens through Raycast.
- Made personal-token setup retain the Android device ID used to obtain the token, matching the upstream `gpsoauth` flow.
- Added **Sync Personal Keep to Root Search**, an explicit local Markdown mirror for personal notes that macOS Spotlight and Raycast File Search can index.

## 0.1.0 — 2026-07-23

- Initial open-source release.
- Added official Google Workspace Keep API search with read-only OAuth.
- Added a no-auth browser search command for every Google Keep account.
