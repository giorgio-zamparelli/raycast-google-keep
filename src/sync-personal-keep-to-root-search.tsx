import { Action, ActionPanel, Alert, confirmAlert, Detail, Icon, showToast, Toast } from "@raycast/api";
import { usePromise } from "@raycast/utils";
import { useState } from "react";
import {
  clearPersonalKeepMirror,
  getPersonalKeepStatus,
  personalKeepMirrorDirectory,
  syncPersonalKeepMirror,
} from "./personal-keep-bridge";
import { bridgeErrorDescription, type PersonalKeepMirrorResult } from "./personal-keep-protocol";
import SetupPersonalGoogleKeep from "./setup-personal-google-keep";

const RAYCAST_FILE_SEARCH_URL = "https://manual.raycast.com/file-search";

export default function SyncPersonalKeepToRootSearch() {
  const { data: status, error, isLoading, revalidate } = usePromise(getPersonalKeepStatus, []);
  const [mirror, setMirror] = useState<PersonalKeepMirrorResult>();
  const [isWorking, setIsWorking] = useState(false);
  const mirrorDirectory = personalKeepMirrorDirectory();
  const canSync = Boolean(status?.configured);

  return (
    <Detail
      isLoading={isLoading || isWorking}
      markdown={mirrorMarkdown({ mirror, mirrorDirectory, status, statusError: error })}
      navigationTitle="Sync Personal Keep to Root Search"
      actions={
        <ActionPanel>
          {canSync ? (
            <Action
              title="Sync Local Mirror Now"
              icon={Icon.ArrowClockwise}
              onAction={async () => {
                const confirmed = await confirmAlert({
                  title: "Sync Google Keep notes to Root Search?",
                  message:
                    "This writes complete personal Google Keep note text to local Markdown files. macOS Spotlight and Raycast can search those files, and their contents may appear in other local search tools or backups. Disconnecting the account does not remove this mirror.",
                  primaryAction: {
                    title: "Sync Local Mirror",
                    style: Alert.ActionStyle.Destructive,
                  },
                });

                if (!confirmed) return;

                setIsWorking(true);
                const toast = await showToast({
                  style: Toast.Style.Animated,
                  title: "Syncing Google Keep Root Search mirror",
                });

                try {
                  const result = await syncPersonalKeepMirror();
                  setMirror(result);
                  toast.style = Toast.Style.Success;
                  toast.title = "Google Keep Root Search mirror synced";
                  toast.message = `${result.notes} notes · ${result.written} updated · ${result.removed} removed`;
                } catch (syncError) {
                  toast.style = Toast.Style.Failure;
                  toast.title = "Unable to sync Google Keep mirror";
                  toast.message = bridgeErrorDescription(syncError);
                } finally {
                  setIsWorking(false);
                  revalidate();
                }
              }}
            />
          ) : (
            <Action.Push
              title="Set up Personal Keep Proof of Concept"
              icon={Icon.Gear}
              target={<SetupPersonalGoogleKeep />}
            />
          )}
          <Action
            title="Remove Local Mirror"
            icon={Icon.Trash}
            style={Action.Style.Destructive}
            onAction={async () => {
              const confirmed = await confirmAlert({
                title: "Remove the local Google Keep mirror?",
                message:
                  "This removes only generated mirror files that have not been changed outside this extension. It leaves unrelated files alone, but Spotlight and Raycast may take time to remove old search entries.",
                primaryAction: {
                  title: "Remove Local Mirror",
                  style: Alert.ActionStyle.Destructive,
                },
              });

              if (!confirmed) return;

              setIsWorking(true);
              try {
                const result = await clearPersonalKeepMirror();
                setMirror(result);
                await showToast({
                  style: Toast.Style.Success,
                  title: "Local Google Keep mirror removed",
                  message: `${result.removed} generated note files removed`,
                });
              } catch (clearError) {
                await showToast({
                  style: Toast.Style.Failure,
                  title: "Unable to remove local mirror",
                  message: bridgeErrorDescription(clearError),
                });
              } finally {
                setIsWorking(false);
                revalidate();
              }
            }}
          />
          <Action.ShowInFinder path={mirrorDirectory} />
          <Action.CopyToClipboard title="Copy Mirror Folder Path" content={mirrorDirectory} />
          <Action.OpenInBrowser title="Read Raycast File Search Setup" icon={Icon.Book} url={RAYCAST_FILE_SEARCH_URL} />
          <Action title="Refresh Connection Status" icon={Icon.ArrowClockwise} onAction={revalidate} />
        </ActionPanel>
      }
    />
  );
}

interface MirrorMarkdownOptions {
  mirror?: PersonalKeepMirrorResult;
  mirrorDirectory: string;
  status?: Awaited<ReturnType<typeof getPersonalKeepStatus>>;
  statusError?: unknown;
}

function mirrorMarkdown({ mirror, mirrorDirectory, status, statusError }: MirrorMarkdownOptions): string {
  if (statusError) {
    return `# Unable to inspect the local Keep companion\n\n${bridgeErrorDescription(statusError)}\n\nYou can still remove an existing local mirror after fixing the configured Python executable.`;
  }

  const syncStatus = mirror
    ? `- Latest sync in this Raycast session: **${mirror.notes} notes**, ${mirror.written} updated, ${mirror.removed} removed, ${mirror.unchanged} unchanged`
    : "- Latest sync in this Raycast session: not run";
  const connectionStatus = status?.configured ? "connected" : "not connected";

  return `# Personal Google Keep in Root Search

This is an explicit, manual mirror—not a background sync. **Sync Local Mirror Now** writes complete personal Google Keep notes to private Markdown files in:

\`${mirrorDirectory}\`

## Privacy

The mirror contains full note text so macOS Spotlight and Raycast can search it. That makes the content available to local search, potentially backups, and other software running as you. It remains on disk after you disconnect Google Keep until you choose **Remove Local Mirror**.

## Required Raycast settings

1. In **Raycast Settings → File Search**, turn on **Content Search**.
2. Ensure macOS Spotlight does not exclude the mirror folder.
3. In **Raycast Settings → Launcher → Customize Search**, enable **Files** (called **Include Files in Root Search** on some versions).
4. After syncing, wait for Spotlight, then run Raycast's **Index Files** command if results do not appear yet.

With those settings, ⌘Space → \`DodoDentist LLC\` can show matching note files directly in Root Search. Open a result to inspect its local read-only mirror.

## Status

- Personal Keep connection: **${connectionStatus}**
${syncStatus}`;
}
