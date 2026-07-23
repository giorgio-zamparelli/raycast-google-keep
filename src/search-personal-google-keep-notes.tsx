import { Action, ActionPanel, Icon, LaunchProps, List } from "@raycast/api";
import { usePromise } from "@raycast/utils";
import { useEffect, useState } from "react";
import PersonalNoteDetail from "./personal-note-detail";
import { searchPersonalKeepNotes } from "./personal-keep-bridge";
import { bridgeErrorDescription } from "./personal-keep-protocol";
import { initialPersonalKeepQuery } from "./personal-keep-query";
import SetupPersonalGoogleKeep from "./setup-personal-google-keep";
import { googleKeepSearchUrl } from "./google-keep-url";

type SearchPersonalGoogleKeepNotesProps = LaunchProps<{
  arguments: {
    query?: string;
  };
}>;

const SEARCH_DEBOUNCE_MS = 350;

export default function SearchPersonalGoogleKeepNotes({
  arguments: { query: argumentQuery },
  fallbackText,
}: SearchPersonalGoogleKeepNotesProps) {
  const [query, setQuery] = useState(() => initialPersonalKeepQuery(argumentQuery, fallbackText));
  const debouncedQuery = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  const { data: notes, error, isLoading, revalidate } = usePromise(searchPersonalKeepNotes, [debouncedQuery]);

  if (error) {
    return <LoadError query={query} error={error} />;
  }

  const waitingForQuery = query !== debouncedQuery;

  return (
    <List
      filtering={false}
      isLoading={isLoading || waitingForQuery}
      onSearchTextChange={setQuery}
      searchBarPlaceholder="Search personal Google Keep notes…"
      searchText={query}
    >
      {(notes ?? []).map((note) => (
        <List.Item
          key={note.id}
          accessories={note.updatedAt ? [{ date: new Date(note.updatedAt) }] : undefined}
          icon={note.isList ? Icon.List : Icon.TextDocument}
          subtitle={note.snippet}
          title={note.title}
          actions={
            <ActionPanel>
              <Action.Push
                title="Show Note"
                icon={Icon.Eye}
                target={<PersonalNoteDetail id={note.id} query={query} />}
              />
              {note.url ? (
                <Action.OpenInBrowser title="Open Note in Google Keep" icon={Icon.Globe} url={note.url} />
              ) : null}
              <Action.OpenInBrowser
                title="Open Matching Search in Google Keep"
                icon={Icon.MagnifyingGlass}
                url={googleKeepSearchUrl(query.trim() || note.title)}
              />
              <Action title="Refresh Search" icon={Icon.ArrowClockwise} onAction={revalidate} />
              <Action.Push
                title="Set up Personal Keep Proof of Concept"
                icon={Icon.Gear}
                target={<SetupPersonalGoogleKeep />}
              />
            </ActionPanel>
          }
        />
      ))}
      {!isLoading && !waitingForQuery && notes?.length === 0 ? (
        <List.EmptyView
          icon={Icon.MagnifyingGlass}
          title={query ? "No matching personal Google Keep notes" : "No personal Google Keep notes found"}
          description={
            query
              ? "Try another term, or refresh after changing a note in Google Keep."
              : "Set up the experimental local companion, then refresh this search."
          }
          actions={
            <ActionPanel>
              <Action title="Refresh Search" icon={Icon.ArrowClockwise} onAction={revalidate} />
              <Action.Push
                title="Set up Personal Keep Proof of Concept"
                icon={Icon.Gear}
                target={<SetupPersonalGoogleKeep />}
              />
              <Action.OpenInBrowser title="Search in Google Keep Instead" url={googleKeepSearchUrl(query)} />
            </ActionPanel>
          }
        />
      ) : null}
    </List>
  );
}

function LoadError({ query, error }: { query: string; error: unknown }) {
  return (
    <List>
      <List.EmptyView
        icon={Icon.ExclamationMark}
        title="Unable to search personal Google Keep"
        description={bridgeErrorDescription(error)}
        actions={
          <ActionPanel>
            <Action.Push
              title="Set up Personal Keep Proof of Concept"
              icon={Icon.Gear}
              target={<SetupPersonalGoogleKeep />}
            />
            <Action.OpenInBrowser title="Search in Google Keep Instead" url={googleKeepSearchUrl(query)} />
          </ActionPanel>
        }
      />
    </List>
  );
}

function useDebouncedValue(value: string, delay: number): string {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timeout);
  }, [delay, value]);

  return debouncedValue;
}
