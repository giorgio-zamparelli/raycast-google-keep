import { Action, ActionPanel, Detail, Icon } from "@raycast/api";
import { googleKeepSearchUrl } from "./google-keep-url";
import { formatNote } from "./search";
import type { KeepNote } from "./types";

interface NoteDetailProps {
  note: KeepNote;
  query: string;
}

export default function NoteDetail({ note, query }: NoteDetailProps) {
  const searchQuery = query.trim() || note.title;

  return (
    <Detail
      markdown={noteMarkdown(note)}
      metadata={
        <Detail.Metadata>
          <Detail.Metadata.Label title="Type" text={note.isList ? "Checklist" : "Note"} />
          {note.updatedAt ? <Detail.Metadata.Label title="Updated" text={formatDate(note.updatedAt)} /> : null}
          {note.createdAt ? <Detail.Metadata.Label title="Created" text={formatDate(note.createdAt)} /> : null}
        </Detail.Metadata>
      }
      actions={
        <ActionPanel>
          <Action.OpenInBrowser
            title="Open Matching Search in Google Keep"
            icon={Icon.MagnifyingGlass}
            url={googleKeepSearchUrl(searchQuery)}
          />
          <Action.CopyToClipboard title="Copy Note" content={formatNote(note)} />
          <Action.CopyToClipboard title="Copy Title" content={note.title} />
        </ActionPanel>
      }
    />
  );
}

function noteMarkdown(note: KeepNote): string {
  const safeTitle = escapeMarkdown(note.title);
  const safeText = (note.text || "Empty note").replaceAll("```", "``​`");

  return `# ${safeTitle}\n\n\`\`\`text\n${safeText}\n\`\`\``;
}

function escapeMarkdown(value: string): string {
  return value.replace(/([\\`*_{}[\]<>#+.!|()-])/g, "\\$1");
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
