import { getPreferenceValues } from "@raycast/api";
import { OAuthService } from "@raycast/utils";
import type { ExtensionPreferences } from "./types";

const GOOGLE_KEEP_READONLY_SCOPE = "https://www.googleapis.com/auth/keep.readonly";

let googleKeepOAuth: OAuthService | undefined;

export function googleKeep(): OAuthService {
  if (googleKeepOAuth) return googleKeepOAuth;

  const { googleClientId } = getPreferenceValues<ExtensionPreferences>();
  const clientId = googleClientId?.trim();

  if (!clientId) {
    throw new Error(
      "Google OAuth Client ID is not configured. Add one in the extension preferences; see the README for Workspace setup.",
    );
  }

  googleKeepOAuth = OAuthService.google({
    clientId,
    scope: GOOGLE_KEEP_READONLY_SCOPE,
  });

  return googleKeepOAuth;
}
