export type ChatRole = "system" | "user" | "assistant" | "tool";

export type ChatMessage = {
  role: ChatRole;
  content?: string | null;
  tool_call_id?: string;
  tool_calls?: ToolCall[];
};

export type ToolCall = {
  id?: string;
  type?: string;
  function?: {
    name?: string;
    arguments?: string;
  };
};

export type SourceEntry = {
  path: string;
  label: string;
  description: string;
  size_bytes: number;
};

export type TimingRow = {
  phase: string;
  status: string;
  seconds: number;
  details?: string;
};

export type FileRef = {
  id: string;
  name: string;
  kind: "artifact" | "trace";
  mime_type: string;
  size_bytes: number;
  url: string;
};

export type ToolPayload = {
  status: string;
  run_id: string | null;
  report_markdown: string;
  artifact_paths: string[];
  citation_summary: string[];
  trace_paths: string[];
  artifacts: FileRef[];
  traces: FileRef[];
  needs_clarification?: {
    question: string;
    missing_fields: string[];
    details: Record<string, unknown>;
  };
  error?: string;
};

export type ChatResult = {
  messages: ChatMessage[];
  assistant_message: ChatMessage;
  tool_envelopes: ToolPayload[];
};

export type StartChatResponse = {
  request_id: string;
  events_url: string;
  status: string;
};

export type RunEventsResponse = {
  request_id: string;
  status: "running" | "complete" | "error";
  timings: TimingRow[];
  result: ChatResult | null;
  error: string | null;
};
