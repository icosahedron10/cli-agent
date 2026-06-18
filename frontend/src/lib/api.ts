import type {
  ChatMessage,
  RunEventsResponse,
  SourceEntry,
  StartChatResponse,
} from "./types";

const DEFAULT_BACKEND_URL = "http://localhost:8765";

export function backendUrl(path = "") {
  const base = (process.env.NEXT_PUBLIC_BACKEND_URL || DEFAULT_BACKEND_URL).replace(/\/$/, "");
  if (!path) {
    return base;
  }
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function fetchSources(): Promise<SourceEntry[]> {
  const payload = await fetchJson<{ sources: SourceEntry[] }>("/sources");
  return payload.sources;
}

export async function startChat(messages: ChatMessage[], prompt: string): Promise<StartChatResponse> {
  return fetchJson<StartChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({ messages, prompt }),
  });
}

export async function fetchRunEvents(eventsUrl: string): Promise<RunEventsResponse> {
  return fetchJson<RunEventsResponse>(eventsUrl);
}

export async function fetchText(path: string): Promise<string> {
  const response = await fetch(backendUrl(path));
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.text();
}

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(backendUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(await responseError(response));
  }
  return response.json() as Promise<T>;
}

async function responseError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: string };
    return payload.error || `${response.status} ${response.statusText}`;
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}
