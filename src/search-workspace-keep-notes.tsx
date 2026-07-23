import { Action, ActionPanel, Icon, LaunchProps, List, openExtensionPreferences } from "@raycast/api";
import { getAccessToken, usePromise, withAccessToken } from "@raycast/utils";
import { useMemo, useState } from "react";
import { GoogleKeepApiError, listGoogleKeepNotes } from "./keep";
import NoteDetail from "./note-detail";
import { googleKeepSearchUrl } from "./google-keep-url";
import { noteSnippet, searchNotes } from "./search";
import { googleKeep } from "./oauth";

type SearchWorkspaceKeepNotesProps = LaunchProps<{
  arguments: {
    query?: string;
  };
}>;

function SearchWorkspaceKeepNotes({
  arguments: { query: argumentQuery },
  fallbackText,
}: SearchWorkspaceKeepNotesProps) {
  const [query, setQuery] = useState(argumentQuery ?? fallbackText ?? "");
  const { token } = getAccessToken();
  const { data: notes, error, isLoading, revalidate } = usePromise(listGoogleKeepNotes, [token]);
  const matchingNotes = useMemo(() => searchNotes(notes ?? [], query), [notes, query]);

  if (error) {
    return <LoadError query={query} error={error} onRetry={revalidate} />;
  }

  return (
    <List
      filtering={false}
      isLoading={isLoading}
      onSearchTextChange={setQuery}
      searchBarPlaceholder="Search titles, note text, and checklist items…"
      searchText={query}
    >
      {matchingNotes.map((note) => (
        <List.Item
          key={note.name}
          accessories={note.updatedAt ? [{ date: new Date(note.updatedAt) }] : undefined}
          icon={note.isList ? Icon.List : Icon.TextDocument}
          keywords={[note.title, note.text]}
          subtitle={noteSnippet(note, query)}
          title={note.title}
          actions={
            <ActionPanel>
              <Action.Push title="Show Note" icon={Icon.Eye} target={<NoteDetail note={note} query={query} />} />
              <Action.OpenInBrowser
                title="Open Matching Search in Google Keep"
                icon={Icon.MagnifyingGlass}
                url={googleKeepSearchUrl(query.trim() || note.title)}
              />
              <Action.CopyToClipboard title="Copy Note" content={`${note.title}\n\n${note.text}`} />
              <Action.CopyToClipboard title="Copy Title" content={note.title} />
              <Action title="Refresh Notes" icon={Icon.ArrowClockwise} onAction={revalidate} />
            </ActionPanel>
          }
        />
      ))}
      {!isLoading && matchingNotes.length === 0 ? (
        <List.EmptyView
          icon={Icon.MagnifyingGlass}
          title={query ? "No matching Google Keep notes" : "No Google Keep notes found"}
          description={
            query ? "Try a different word or refresh the note list." : "Create a note in Google Keep, then refresh."
          }
          actions={
            <ActionPanel>
              <Action title="Refresh Notes" icon={Icon.ArrowClockwise} onAction={revalidate} />
              <Action.OpenInBrowser title="Open Google Keep" url={googleKeepSearchUrl(query)} />
            </ActionPanel>
          }
        />
      ) : null}
    </List>
  );
}

function LoadError({ query, error, onRetry }: { error: Error; onRetry: () => void; query: string }) {
  const isAccessError = error instanceof GoogleKeepApiError && error.status === 403;
  const description = isAccessError
    ? "Google denied access. Confirm this is a Google Workspace account, the Keep API is enabled, and your Workspace admin approved the OAuth client and keep.readonly scope. Personal Google accounts are not supported by the official API."
    : error.message;

  return (
    <List>
      <List.EmptyView
        icon={Icon.ExclamationMark}
        title="Unable to load Google Keep notes"
        description={description}
        actions={
          <ActionPanel>
            <Action title="Try Again" icon={Icon.ArrowClockwise} onAction={onRetry} />
            <Action title="Open Extension Preferences" icon={Icon.Gear} onAction={openExtensionPreferences} />
            <Action.OpenInBrowser title="Search in Google Keep Instead" url={googleKeepSearchUrl(query)} />
          </ActionPanel>
        }
      />
    </List>
  );
}

export default withAccessToken(googleKeep())(SearchWorkspaceKeepNotes);
