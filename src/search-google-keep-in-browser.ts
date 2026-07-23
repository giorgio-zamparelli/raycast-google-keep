import { LaunchProps, open, showHUD } from "@raycast/api";
import { googleKeepSearchUrl } from "./google-keep-url";

type SearchGoogleKeepInBrowserProps = LaunchProps<{
  arguments: {
    query: string;
  };
}>;

export default async function searchGoogleKeepInBrowser({
  arguments: commandArguments,
}: SearchGoogleKeepInBrowserProps) {
  const query = commandArguments.query.trim();

  await open(googleKeepSearchUrl(query));
  await showHUD(`Searching Google Keep for “${query}”`);
}
