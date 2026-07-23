import { environment, getPreferenceValues } from "@raycast/api";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  parseBridgeResponse,
  PersonalKeepBridgeError,
  type PersonalKeepMirrorResult,
  type PersonalKeepNote,
  type PersonalKeepNotePreview,
  type PersonalKeepStatus,
} from "./personal-keep-protocol";
import type { PersonalKeepPreferences } from "./types";

const BRIDGE_TIMEOUT_MS = 60_000;
const MIRROR_TIMEOUT_MS = 300_000;
const MAX_OUTPUT_BYTES = 4_000_000;

type BridgeOperation = "status" | "disconnect" | "search" | "get" | "sync-mirror" | "clear-mirror";

interface BridgeResult {
  status?: PersonalKeepStatus;
  notes?: PersonalKeepNotePreview[];
  note?: PersonalKeepNote;
  mirror?: PersonalKeepMirrorResult;
  disconnected?: boolean;
}

function bridgePath(): string {
  return join(environment.assetsPath, "personal-keep-bridge.py");
}

function pythonPath(): string {
  const { personalKeepPythonPath } = getPreferenceValues<PersonalKeepPreferences>();
  const configuredPath = personalKeepPythonPath?.trim() || "python3";

  return expandHome(configuredPath);
}

function expandHome(value: string): string {
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));

  return value;
}

function runBridge(operation: BridgeOperation, request?: object): Promise<BridgeResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonPath(), [bridgePath(), operation], {
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const stdoutChunks: Buffer[] = [];
    let outputSize = 0;
    let timedOut = false;
    let settled = false;

    const finish = (handler: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      handler();
    };

    const timeout = setTimeout(
      () => {
        timedOut = true;
        child.kill();
      },
      operation === "sync-mirror" ? MIRROR_TIMEOUT_MS : BRIDGE_TIMEOUT_MS,
    );

    child.stdout.on("data", (chunk: Buffer) => {
      outputSize += chunk.length;

      if (outputSize > MAX_OUTPUT_BYTES) {
        child.kill();
        return;
      }

      stdoutChunks.push(chunk);
    });

    // Third-party Python errors are intentionally discarded: they can contain
    // authentication details and must never reach a Raycast surface or log.
    child.stderr.resume();

    child.on("error", (error: NodeJS.ErrnoException) => {
      finish(() => {
        if (error.code === "ENOENT") {
          reject(
            new PersonalKeepBridgeError(
              "python-not-found",
              "The configured Python executable was not found. Set Personal Keep Python Executable in extension preferences.",
            ),
          );
          return;
        }

        reject(error);
      });
    });

    child.on("close", () => {
      finish(() => {
        if (timedOut) {
          reject(
            new PersonalKeepBridgeError(
              "timeout",
              "The private Google Keep operation did not finish in time. Check your connection and retry.",
            ),
          );
          return;
        }

        if (outputSize > MAX_OUTPUT_BYTES) {
          reject(
            new PersonalKeepBridgeError(
              "response-too-large",
              "The personal Keep companion returned too much data. Narrow the search and retry.",
            ),
          );
          return;
        }

        try {
          resolve(parseBridgeResponse(Buffer.concat(stdoutChunks).toString()) as BridgeResult);
        } catch (error) {
          reject(error);
        }
      });
    });

    if (request) {
      child.stdin.end(JSON.stringify({ version: 1, ...request }));
    } else {
      child.stdin.end();
    }
  });
}

export async function getPersonalKeepStatus(): Promise<PersonalKeepStatus> {
  const response = await runBridge("status");

  if (!response.status) {
    throw new PersonalKeepBridgeError("invalid-response", "The local companion did not return its setup status.");
  }

  return response.status;
}

export async function searchPersonalKeepNotes(query: string): Promise<PersonalKeepNotePreview[]> {
  const response = await runBridge("search", { query });
  return response.notes ?? [];
}

export async function getPersonalKeepNote(id: string): Promise<PersonalKeepNote> {
  const response = await runBridge("get", { id });

  if (!response.note) {
    throw new PersonalKeepBridgeError("invalid-response", "The local companion did not return the selected note.");
  }

  return response.note;
}

export async function disconnectPersonalKeep(): Promise<void> {
  await runBridge("disconnect");
}

export async function syncPersonalKeepMirror(): Promise<PersonalKeepMirrorResult> {
  const response = await runBridge("sync-mirror");

  if (!response.mirror) {
    throw new PersonalKeepBridgeError(
      "invalid-response",
      "The local companion did not return the Root Search mirror status.",
    );
  }

  return response.mirror;
}

export async function clearPersonalKeepMirror(): Promise<PersonalKeepMirrorResult> {
  const response = await runBridge("clear-mirror");

  if (!response.mirror) {
    throw new PersonalKeepBridgeError(
      "invalid-response",
      "The local companion did not return the Root Search mirror status.",
    );
  }

  return response.mirror;
}

export function personalKeepConnectCommand(): string {
  return `${shellQuote(pythonPath())} ${shellQuote(bridgePath())} connect`;
}

export function isPersonalKeepBridgeAvailable(): boolean {
  return existsSync(bridgePath());
}

export function personalKeepMirrorDirectory(): string {
  return join(homedir(), "Google Keep Search");
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}
