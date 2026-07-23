# Google Keep Search for Raycast

Search Google Keep without leaving Raycast.

- **Search Workspace Keep Notes** connects to the official, read-only Google Keep API and searches note titles, note text, and checklist items directly in Raycast.
- **Search Google Keep in Browser** opens Google Keep's own search and works with both personal and Google Workspace accounts.
- Select a result to read and copy the full note; use the browser action to open the equivalent native Keep search.

## Important account support

Google's official Keep API is an **enterprise Google Workspace API**. It is not available for personal `@gmail.com` accounts, and Google positions its production access model around Workspace administrator approval/domain-wide delegation. This extension deliberately does not use undocumented private APIs, cookies, or browser scraping.

| Account type                                             | Raycast note results   | Browser search |
| -------------------------------------------------------- | ---------------------- | -------------- |
| Google Workspace, with administrator-approved API access | Yes                    | Yes            |
| Personal Google / `@gmail.com`                           | No official API access | Yes            |

The Browser command is the reliable choice for personal Google Keep accounts.

## Workspace setup

The Workspace command requests exactly one scope: `https://www.googleapis.com/auth/keep.readonly`. It cannot write, delete, or change the sharing of a note.

1. Create or choose a Google Cloud project and [enable the Google Keep API](https://console.cloud.google.com/apis/library/keep.googleapis.com).
2. Configure the OAuth consent screen for your organization. Your Workspace administrator may need to approve the app/client and the Keep scope before users can authorize it. See Google's [Keep API authorization guide](https://developers.google.com/workspace/keep/api/guides).
3. Create an OAuth client ID:
   - Application type: **iOS**
   - Bundle ID: **`com.raycast`**
4. Copy its client ID (for example, `123456789-abc.apps.googleusercontent.com`) into Raycast's **Google Keep Search** extension preferences.
5. Run **Search Workspace Keep Notes**, then complete the native Raycast/Google OAuth flow.

Raycast uses PKCE and stores OAuth tokens in the system keychain. The extension calls Google directly; it has no backend and does not persist your note content between command runs.

### Why is a client ID required?

Raycast provides an OAuth helper for Google, but it does not provide a shared Google OAuth application for third-party extensions. Google requires an OAuth client appropriate to the requested scopes, so each organization/user supplies its own client ID. No client secret is needed for the iOS/PKCE flow.

## Searching from Raycast

Run **Search Workspace Keep Notes** and type a query such as `DodoDentist`. The extension downloads the available note pages for that command run and filters them locally, because Google's `notes.list` endpoint does not offer a full-text query filter.

Raycast extensions cannot add live third-party records directly to the root-search result list. To get close to the desired keyboard flow, set **Search Workspace Keep Notes** as a Raycast fallback command. Then an unmatched root-search query such as `DodoDentist` is passed into the extension and opens the matching note list. You can also invoke the command normally and enter the query in its optional argument.

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

`npm run lint:raycast` and `npm run build` also validate the `author` field against Raycast. The initial value follows the GitHub owner; update it to your Raycast username if they differ before a Store submission. To publish to the Raycast Store, use `npm run publish`; Raycast will guide you through creating a submission to its extension repository.

## Privacy and security

- Only the `keep.readonly` Google scope is requested for Workspace search.
- OAuth tokens are handled by Raycast's built-in OAuth flow and stored in the system keychain.
- Note text is held in memory only while the command runs. It is not sent to a service operated by this project.
- The browser-search command never requests OAuth access.

## Limitations

- Personal Google accounts do not have supported Google Keep API access.
- The Google Keep API does not expose a documented direct web URL for an individual note, so the browser action opens the equivalent Keep search rather than constructing an unsupported note deep link.
- Attachments, labels, colors, reminders, and archived notes are outside this first search-focused release.

Google Keep and Google Workspace are trademarks of Google LLC. This project is independent and is not affiliated with or endorsed by Google or Raycast.

## License

[MIT](LICENSE)
