import { Action, ActionPanel, Detail, Icon } from "@raycast/api";
import { usePromise } from "@raycast/utils";
import { getPersonalKeepNote } from "./personal-keep-bridge";
import { bridgeErrorDescription } from "./personal-keep-protocol";
import { googleKeepSearchUrl } from "./google-keep-url";

export default function PersonalNoteDetail({ id, query }: { id: string; query: string }) {
  const { data: note, error, isLoading } = usePromise(getPersonalKeepNote, [id]);

  if (error) {
    return <Detail markdown={`# Unable to load note\n\n${bridgeErrorDescription(error)}`} />;
  }

  if (!note) {
    return <Detail isLoading={isLoading} markdown="Loading note…" />;
  }

  const truncatedNotice = note.truncated
    ? "\n\n> This unusually large note was truncated for this proof of concept."
    : "";

  return (
    <Detail
      markdown={`# ${note.title}\n\n${note.text || "_Empty note_"}${truncatedNotice}`}
      navigationTitle={note.title}
      actions={
        <ActionPanel>
          {note.url ? <Action.OpenInBrowser title="Open Note in Google Keep" icon={Icon.Globe} url={note.url} /> : null}
          <Action.OpenInBrowser
            title="Open Matching Search in Google Keep"
            icon={Icon.MagnifyingGlass}
            url={googleKeepSearchUrl(query.trim() || note.title)}
          />
          <Action.CopyToClipboard title="Copy Note" content={`${note.title}\n\n${note.text}`} />
          <Action.CopyToClipboard title="Copy Title" content={note.title} />
        </ActionPanel>
      }
    />
  );
}
