# Google Keep Search for Raycast

Search Google Keep without leaving Raycast.

- **Search Workspace Keep Notes** connects to Google's official, read-only Google Keep API and searches note titles, note text, and checklist items directly in Raycast.
- **Search Personal Google Keep Notes** is an opt-in, local-only, **experimental proof of concept** for personal Gmail accounts. It uses the unsupported `gkeepapi` Android-client protocol.
- **Sync Personal Keep to Root Search** is an explicit, opt-in local Markdown mirror for personal Keep notes. After macOS indexes it, matching note files can appear in Raycast Root Search.
- **Search Google Keep in Browser** opens Google Keep's native search and works with both personal and Workspace accounts.
- Select a result to read and copy the full note; browser actions open the native Keep note or search where available.

## Account support

Google's official Keep API is an enterprise Google Workspace API. It is not available for personal `@gmail.com` accounts. The experimental path exists because `gkeepapi` can communicate with Google's private mobile Keep protocol; it is not a Google-supported integration.

| Account type                                             | Direct Raycast note results                | Browser search |
| -------------------------------------------------------- | ------------------------------------------ | -------------- |
| Google Workspace, with administrator-approved API access | Yes — official API                         | Yes            |
| Personal Google / `@gmail.com`                           | Yes — experimental, local-only private API | Yes            |

The browser command is the safest choice for personal Google Keep accounts. The personal-account POC is for local testing only and should not be considered Store-ready.

## Personal Gmail proof of concept

This path deliberately avoids Cloud OAuth. It uses [`gkeepapi`](https://github.com/kiwiz/gkeepapi), which impersonates the Android Keep client and syncs against an undocumented Google endpoint.

Before using it, understand the trade-offs:

- It is unsupported by Google and can break or be revoked without notice.
- Its **master token has broad Google-account access**; it is not a `keep.readonly` OAuth permission.
- The companion only implements search and note display, but the underlying credential is more powerful than this code path.
- The normal personal-search command uses no backend, telemetry, or note-content cache. Matching data is held in memory only while that command runs. The separate, opt-in Root Search mirror deliberately writes complete notes to local files, as described below.
- The token, active account, and a stable Android device ID are stored only in macOS Keychain. They are never stored in Raycast preferences, command arguments, environment variables, files, or this repository.

Use a disposable Google account for initial testing. Do not paste a Google password, an MFA code, or a browser OAuth cookie anywhere in this extension.

### Install the local companion

The POC needs macOS plus Python 3.10 or newer. On this Mac, Homebrew's Python is available at `/opt/homebrew/bin/python3`; use another Python 3.10+ executable if yours differs.

Create an isolated virtual environment and install the pinned dependencies—never use `sudo`:

```bash
PERSONAL_KEEP_VENV="$HOME/Library/Application Support/Google Keep Search/poc-venv"
/opt/homebrew/bin/python3 -m venv "$PERSONAL_KEEP_VENV"
"$PERSONAL_KEEP_VENV/bin/python" -m pip install --upgrade pip
"$PERSONAL_KEEP_VENV/bin/python" -m pip install -r requirements-personal-keep-poc.txt
```

Then open Raycast Preferences → Extensions → **Google Keep Search**, and set **Personal Keep Python Executable** to:

```text
~/Library/Application Support/Google Keep Search/poc-venv/bin/python
```

Run **Set up Personal Google Keep POC**. Once it reports the prerequisites are ready:

1. Choose **Copy Secure Connect Command**.
2. Paste and run that command in a Terminal window.
3. Read the warning and type `I UNDERSTAND`.
4. From the upstream `gpsoauth.exchange_token` response, retain both the **`Token`** value (the gkeepapi master token) and the 16-character lowercase Android ID used for the exchange. Do not use the response's `Auth` value.
5. Enter your Google email, the master token, and that **same** Android device ID at the hidden Terminal prompts.
6. Return to Raycast and choose **Refresh Setup Status**.

The project intentionally does not obtain the token for you. Follow the [gkeepapi authentication documentation](https://gkeepapi.readthedocs.io/en/latest/) at your own risk; the token must be the `Token` value from the master-token response, not a raw browser OAuth cookie or its `Auth` field.

To remove local access, run **Set up Personal Google Keep POC** and choose **Disconnect Personal Keep**. This deletes exactly the POC's Keychain items. It does **not** delete an existing Root Search mirror; remove that separately with **Sync Personal Keep to Root Search**. If a token may have leaked, also revoke or secure the account through Google Account security controls.

### Searching personal notes

Run **Search Personal Google Keep Notes** and type a query such as `DodoDentist LLC`. The local companion refreshes from Keep, performs case-insensitive matching over title and text locally, returns only result previews to Raycast, and fetches full note text only after you select a result.

### Show matching notes directly in Root Search (opt-in)

Raycast's public extension API cannot insert a live Google Keep record into its native Root Search list. The **Sync Personal Keep to Root Search** command uses a supported alternative: it writes a local Markdown mirror that Raycast File Search and macOS Spotlight can index.

1. Run **Sync Personal Keep to Root Search**.
2. Read the privacy warning and choose **Sync Local Mirror**. This is a manual action, not a background sync.
3. In **Raycast Settings → File Search**, turn on **Content Search**.
4. Ensure macOS Spotlight does not exclude `~/Google Keep Search`.
5. In **Raycast Settings → Launcher → Customize Search**, enable **Files** (called **Include Files in Root Search** on some Raycast versions).
6. Wait for Spotlight to index the files. If needed, run Raycast's **Index Files** command.

The mirror is stored in `~/Google Keep Search`. It contains complete note text so that typing ⌘Space → `DodoDentist LLC` can show a matching generated note file directly in Root Search. Opening that result opens the local, read-only mirror rather than a live Keep note.

This is intentionally a privacy trade-off: the full note content is now on disk and may be searchable by other local software running as you or included in backups. It stays on disk after disconnecting the Google account until you choose **Remove Local Mirror** from the same command. Removal is deliberately cautious and refuses to delete a mirror file that was changed outside the extension.

### Use the no-local-copy fallback flow

To make ⌘Space → `DodoDentist LLC` → Return open its matching Keep results:

1. Open **Raycast Settings → Launcher → Fallback Commands**.
2. Add **Search Personal Google Keep Notes** and place it first (or make it the only fallback).
3. Press ⌘Space, type `DodoDentist LLC`, then press Return.

Raycast sends the root-search text to the command as its fallback text, so the Keep result list opens already searched. Fallback commands appear only when Root Search has no normal match. This keeps note content off disk, unlike the optional local mirror above.

## Workspace setup (official API)

The Workspace command requests exactly one scope: `https://www.googleapis.com/auth/keep.readonly`. It cannot write, delete, or change the sharing of a note.

1. Create or choose a Google Cloud project and [enable the Google Keep API](https://console.cloud.google.com/apis/library/keep.googleapis.com).
2. Configure the OAuth consent screen for your organization. Your Workspace administrator may need to approve the app/client and the Keep scope before users can authorize it. See Google's [Keep API authorization guide](https://developers.google.com/workspace/keep/api/guides).
3. Create an OAuth client ID:
   - Application type: **iOS**
   - Bundle ID: **`com.raycast`**
4. Run **Search Workspace Keep Notes** in Raycast. On its first run, Raycast opens the command preferences; paste the client ID there (for example, `123456789-abc.apps.googleusercontent.com`).
5. Run the command again, then complete the native Raycast/Google OAuth flow.

Raycast uses PKCE and stores OAuth tokens in the system keychain. The extension calls Google directly; it has no backend and does not persist your note content between command runs.

### Why is a client ID required?

Raycast provides an OAuth helper for Google, but it does not provide a shared Google OAuth application for third-party extensions. Google requires an OAuth client appropriate to the requested scopes, so each organization/user supplies its own client ID. No client secret is needed for the iOS/PKCE flow.

## Browser search

For a fast, no-auth launcher, invoke **Search Google Keep in Browser** with a query. It opens Google Keep's native search URL in your default browser, where your existing Google session applies.

## Development

```bash
npm install
npm run dev
```

Before opening a pull request or publishing:

```bash
npm run format
npm run lint
npm test
npm run lint:raycast
npm run build
```

`npm run lint:raycast` and `npm run build` also validate the `author` field against Raycast. The initial value follows the GitHub owner; update it to your Raycast username if they differ before a Store submission. Do not submit the personal Gmail POC to the Raycast Store without a separate security and policy review.

## Privacy and security

- The official Workspace command requests only `keep.readonly`.
- The personal Gmail POC never receives a password, MFA code, browser cookie, or token through Raycast; its Terminal-only companion writes the master token directly to macOS Keychain.
- Personal-search previews contain only title, a short snippet, metadata, and a Keep URL. Full text is fetched on explicit selection and never cached.
- Only after an explicit confirmation, **Sync Personal Keep to Root Search** writes complete personal note text to private Markdown files in `~/Google Keep Search`. Those files are searchable by Spotlight/Raycast and may be visible to other local search tools or backups; disconnecting does not remove them.
- The browser-search command never requests OAuth access.

## Limitations

- Personal Gmail access depends on an undocumented API and a broad master token; it is not a supported Google integration.
- The POC uses a private sync endpoint, which is a POST even when this implementation submits no note changes. Treat its behavior as read-only by convention, not by permission scope.
- Attachments, labels, colors, reminders, and archived-note controls are outside this first search-focused release.
- Raycast extensions cannot add live third-party records directly to the Root Search result list. The opt-in mirror makes locally indexed file results possible, but it is manual, may take time to index, and is not a live Google Keep view.

Google Keep and Google Workspace are trademarks of Google LLC. This project is independent and is not affiliated with or endorsed by Google or Raycast.

## License

[MIT](LICENSE)
