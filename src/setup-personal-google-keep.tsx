import {
  Action,
  ActionPanel,
  Alert,
  confirmAlert,
  Detail,
  Icon,
  openExtensionPreferences,
  showToast,
  Toast,
} from "@raycast/api";
import { usePromise } from "@raycast/utils";
import {
  disconnectPersonalKeep,
  getPersonalKeepStatus,
  isPersonalKeepBridgeAvailable,
  personalKeepConnectCommand,
} from "./personal-keep-bridge";
import { bridgeErrorDescription } from "./personal-keep-protocol";
import { googleKeepSearchUrl } from "./google-keep-url";

const GKEEPAPI_DOCUMENTATION_URL = "https://gkeepapi.readthedocs.io/en/latest/";
const RAYCAST_FALLBACK_COMMANDS_URL = "https://manual.raycast.com/settings#fallback-commands";

export default function SetupPersonalGoogleKeep() {
  const { data: status, error, isLoading, revalidate } = usePromise(getPersonalKeepStatus, []);

  if (error) {
    return <Detail markdown={`# Unable to inspect the local companion\n\n${bridgeErrorDescription(error)}`} />;
  }

  const markdown = status ? setupMarkdown(status) : "Loading local companion status…";
  const canConnect = Boolean(
    status?.supportedPython && status.dependencies.gkeepapi && status.dependencies.keyring && status.keychainAvailable,
  );
  const connectCommand = personalKeepConnectCommand();

  return (
    <Detail
      isLoading={isLoading}
      markdown={markdown}
      navigationTitle="Set Up Personal Google Keep POC"
      actions={
        <ActionPanel>
          {canConnect ? (
            <Action.CopyToClipboard
              title="Copy Secure Connect Command"
              icon={Icon.Terminal}
              content={connectCommand}
              shortcut={{ modifiers: ["cmd"], key: "c" }}
            />
          ) : null}
          <Action title="Refresh Setup Status" icon={Icon.ArrowClockwise} onAction={revalidate} />
          {status?.configured ? (
            <Action
              title="Disconnect Personal Keep"
              icon={Icon.Trash}
              style={Action.Style.Destructive}
              onAction={async () => {
                const confirmed = await confirmAlert({
                  title: "Disconnect Personal Google Keep?",
                  message:
                    "This deletes the saved master token, active account, and device ID from macOS Keychain. It does not delete the optional local Root Search mirror.",
                  primaryAction: {
                    title: "Disconnect",
                    style: Alert.ActionStyle.Destructive,
                  },
                });

                if (!confirmed) return;

                try {
                  await disconnectPersonalKeep();
                  await showToast({ style: Toast.Style.Success, title: "Personal Google Keep disconnected" });
                  revalidate();
                } catch (disconnectError) {
                  await showToast({
                    style: Toast.Style.Failure,
                    title: "Unable to disconnect",
                    message: bridgeErrorDescription(disconnectError),
                  });
                }
              }}
            />
          ) : null}
          <Action.OpenInBrowser
            title="Read Gkeepapi Token Documentation"
            icon={Icon.Book}
            url={GKEEPAPI_DOCUMENTATION_URL}
          />
          <Action.OpenInBrowser
            title="Read Root Search Fallback Setup"
            icon={Icon.MagnifyingGlass}
            url={RAYCAST_FALLBACK_COMMANDS_URL}
          />
          <Action.OpenInBrowser
            title="Use Google Keep Browser Search"
            icon={Icon.Globe}
            url={googleKeepSearchUrl("")}
          />
          <Action title="Open Extension Preferences" icon={Icon.Gear} onAction={openExtensionPreferences} />
        </ActionPanel>
      }
    />
  );
}

function setupMarkdown(status: NonNullable<Awaited<ReturnType<typeof getPersonalKeepStatus>>>): string {
  const bridgeAvailable = isPersonalKeepBridgeAvailable();
  const prerequisites = [
    `- Bundled local bridge: ${bridgeAvailable ? "ready" : "missing"}`,
    `- Python: ${status.pythonVersion}${status.supportedPython ? "" : " (Python 3.10+ required)"}`,
    `- gkeepapi: ${status.dependencies.gkeepapi ? "installed" : "not installed"}`,
    `- keyring: ${status.dependencies.keyring ? "installed" : "not installed"}`,
    `- macOS Keychain: ${status.keychainAvailable ? "available" : "unavailable"}`,
  ].join("\n");

  if (status.configured) {
    return `# Personal Google Keep POC is connected\n\nThis local, experimental bridge is ready to search your personal Google Keep notes.\n\n${prerequisites}\n\n## Show matching files directly in Root Search (opt-in)\n\nRun **Sync Personal Keep to Root Search** and confirm its privacy warning. It manually writes complete note text to local Markdown files in \`~/Google Keep Search\`; it is not a background sync.\n\n1. In **Raycast Settings → File Search**, turn on **Content Search**.\n2. Ensure macOS Spotlight does not exclude the mirror folder.\n3. In **Raycast Settings → Launcher → Customize Search**, enable **Files** (called **Include Files in Root Search** on some versions).\n4. Wait for indexing, then run Raycast's **Index Files** command if needed.\n\nWith those settings, ⌘Space → \`DodoDentist LLC\` can show matching local note files in Root Search. The full note text remains on disk, may be searched by other local software or backups, and remains after disconnecting until you choose **Remove Local Mirror**.\n\n## Use the no-local-copy fallback flow\n\n1. Open Raycast Settings → **Launcher** → **Fallback Commands**.\n2. Add **Search Personal Google Keep Notes** and place it first (or make it the only fallback).\n3. Press ⌘Space, type a query such as \`DodoDentist LLC\`, then press Return.\n\nRaycast passes that root-search text to this command, which then shows matching Keep notes. Fallback commands appear only when the root query has no normal Raycast match.\n\nDisconnect removes the saved credential and device ID from macOS Keychain, but does not remove an existing local Root Search mirror.`;
  }

  if (
    !status.supportedPython ||
    !status.dependencies.gkeepapi ||
    !status.dependencies.keyring ||
    !status.keychainAvailable
  ) {
    return `# Set up the experimental personal-account POC\n\nThis is **not** Google's supported Keep API. It impersonates the Android Keep client through gkeepapi. A master token has broad account access, can stop working without notice, and is not a read-only OAuth scope. Start with a disposable Google account.\n\nThe extension never collects your Google password, MFA code, browser cookies, or master token. Normal personal search does not persist note content or use a backend. The separate, opt-in **Sync Personal Keep to Root Search** command writes complete notes to local Markdown files after an explicit confirmation.\n\n## Prerequisites\n\n${prerequisites}\n\n1. Create a Python 3.10+ virtual environment outside this repository.\n2. Install exactly: \`gkeepapi==0.17.1\`, \`gpsoauth==2.0.0\`, and \`keyring==25.6.0\`.\n3. Set **Personal Keep Python Executable** in this extension's preferences to that virtual environment's Python.\n4. Refresh this page.\n\nThe README has the full copy-paste setup and recovery steps.`;
  }

  return `# Connect the experimental personal-account POC\n\nThe prerequisites are ready. Use **Copy Secure Connect Command**, paste it into a Terminal window, and run it. The script will:\n\n1. Require you to type \`I UNDERSTAND\`.\n2. Prompt for your email and gkeepapi **master token** with hidden input.\n3. Store the token, active account, and a stable Android device ID only in macOS Keychain.\n\nDo **not** enter your Google password, MFA code, or browser OAuth cookie. This project cannot obtain a token for you. After the command succeeds, return here and choose **Refresh Setup Status**. You can then use **Sync Personal Keep to Root Search** if you explicitly want full note text written to a local, Spotlight-indexed mirror.`;
}
