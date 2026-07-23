export interface PersonalKeepStatus {
  pythonVersion: string;
  supportedPython: boolean;
  dependencies: {
    gkeepapi: boolean;
    keyring: boolean;
  };
  keychainAvailable: boolean;
  configured: boolean;
}

export interface PersonalKeepNotePreview {
  id: string;
  title: string;
  snippet: string;
  isList: boolean;
  updatedAt?: string | null;
  url?: string | null;
}

export interface PersonalKeepNote extends PersonalKeepNotePreview {
  text: string;
  truncated: boolean;
}

export interface PersonalKeepMirrorResult {
  directory: string;
  notes: number;
  written: number;
  removed: number;
  unchanged: number;
}

interface BridgeErrorPayload {
  code?: string;
  message?: string;
}

interface BridgeResponse {
  version?: number;
  ok?: boolean;
  error?: BridgeErrorPayload;
  status?: PersonalKeepStatus;
  notes?: PersonalKeepNotePreview[];
  note?: PersonalKeepNote;
  mirror?: PersonalKeepMirrorResult;
  disconnected?: boolean;
}

export class PersonalKeepBridgeError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "PersonalKeepBridgeError";
  }
}

export function parseBridgeResponse(output: string): BridgeResponse {
  let response: BridgeResponse;

  try {
    response = JSON.parse(output) as BridgeResponse;
  } catch {
    throw new PersonalKeepBridgeError(
      "invalid-response",
      "The local personal Keep companion returned an unreadable response. Run the setup command and reconnect it.",
    );
  }

  if (response.version !== 1 || typeof response.ok !== "boolean") {
    throw new PersonalKeepBridgeError(
      "invalid-response",
      "The local personal Keep companion uses an unsupported response format. Update the local extension and try again.",
    );
  }

  if (!response.ok) {
    throw new PersonalKeepBridgeError(
      response.error?.code ?? "bridge-error",
      response.error?.message ?? "The local personal Keep companion could not complete the request.",
    );
  }

  return response;
}

export function bridgeErrorDescription(error: unknown): string {
  if (error instanceof PersonalKeepBridgeError) return error.message;

  return "The local personal Keep companion could not be started. Check the configured Python executable and retry.";
}
