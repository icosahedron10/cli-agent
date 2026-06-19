"use client";

import { Download, RefreshCw, Send, SquareTerminal } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { backendUrl, fetchRunEvents, fetchSources, fetchText, startChat } from "@/lib/api";
import type { ChatMessage, FileRef, SourceEntry, TimingRow, ToolCall, ToolPayload } from "@/lib/types";

const POLL_INTERVAL_MS = 700;
const RUN_POLL_TIMEOUT_MS = 10 * 60 * 1000;

const STARTERS = [
  {
    label: "source-search: 0 HP combat rule",
    prompt:
      'Use source_search with source_paths ["5e PHB/chapters/10 - Chapter 9 - Combat.pdf"] to answer: what does the PHB say happens when a creature drops to 0 hit points? Include citations.',
  },
  {
    label: "auto-analysis: equipment totals",
    prompt:
      'Use auto_analysis with source_paths ["5e PHB/chapters/05 - Chapter 5 - Equipment.pdf"] to calculate the total gp cost and total weight for this equipment loadout: chain mail, shield, longsword, and 2 handaxes. Create a pair of stacked bar chart PNG artifacts: one for gp cost by item and one for weight by item. Include a short table and cite the source.',
  },
];

type TracePreview = {
  file: FileRef;
  text: string;
  parsed: unknown | null;
};

export function ChatWorkbench() {
  const [sources, setSources] = useState<SourceEntry[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [prompt, setPrompt] = useState("");
  const [timings, setTimings] = useState<TimingRow[]>([]);
  const [runningRequestId, setRunningRequestId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tracePreview, setTracePreview] = useState<TracePreview | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const isRunning = runningRequestId !== null;
  const visibleMessages = useMemo(() => messages.filter(isVisibleMessage), [messages]);
  const toolCalls = useMemo(() => collectToolCalls(messages), [messages]);
  const toolPayloads = useMemo(() => collectToolPayloads(messages), [messages]);

  useEffect(() => {
    void loadSources();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, toolPayloads.length]);

  async function loadSources() {
    try {
      setSources(await fetchSources());
      setError(null);
    } catch (fetchError) {
      setError(errorMessage(fetchError));
    }
  }

  async function submitPrompt(nextPrompt: string) {
    const trimmed = nextPrompt.trim();
    if (!trimmed || isRunning) {
      return;
    }

    const history = messages;
    setPrompt("");
    setError(null);
    setTracePreview(null);
    setTimings([]);
    setMessages([...history, { role: "user", content: trimmed }]);

    try {
      const started = await startChat(history, trimmed);
      setRunningRequestId(started.request_id);
      await pollRun(started.events_url);
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setRunningRequestId(null);
    }
  }

  async function pollRun(eventsUrl: string) {
    const startedAt = Date.now();
    for (;;) {
      const elapsedMs = Date.now() - startedAt;
      if (elapsedMs >= RUN_POLL_TIMEOUT_MS) {
        throw new Error("Backend run timed out. You can send another prompt.");
      }
      const eventPayload = await fetchRunEvents(eventsUrl);
      setTimings(eventPayload.timings);
      if (eventPayload.status === "running") {
        const remainingMs = RUN_POLL_TIMEOUT_MS - (Date.now() - startedAt);
        if (remainingMs <= 0) {
          throw new Error("Backend run timed out. You can send another prompt.");
        }
        await wait(Math.min(POLL_INTERVAL_MS, remainingMs));
        continue;
      }
      if (eventPayload.status === "complete" && eventPayload.result) {
        setMessages(eventPayload.result.messages);
        return;
      }
      throw new Error(eventPayload.error || "Backend run failed");
    }
  }

  async function previewTrace(file: FileRef) {
    try {
      const text = redactTrace(await fetchText(file.url));
      setTracePreview({ file, text, parsed: parseJsonMaybe(text) });
    } catch (previewError) {
      setError(errorMessage(previewError));
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitPrompt(prompt);
  }

  return (
    <main className="app-shell">
      <aside className="source-sidebar">
        <div className="sidebar-header">
          <h1>CLI Source Tool</h1>
          <button type="button" className="icon-button" onClick={() => void loadSources()} aria-label="Reload sources">
            <RefreshCw size={16} />
          </button>
        </div>
        <div className="source-list">
          {sources.map((source) => (
            <div className="source-item" key={source.path}>
              <strong>{source.label}</strong>
              <code>{source.path}</code>
              {source.description ? <p>{source.description}</p> : null}
            </div>
          ))}
          {!sources.length && <p className="empty-copy">No approved sources loaded.</p>}
        </div>
      </aside>

      <section className="workbench">
        <header className="topbar">
          <div>
            <h2>Source and Auto Analysis</h2>
            <p>{backendUrl()}</p>
          </div>
          <div className={`status-label ${isRunning ? "is-running" : ""}`}>{isRunning ? "Running" : "Idle"}</div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <div className="starter-row">
          {STARTERS.map((starter) => (
            <button
              type="button"
              key={starter.label}
              className="starter-button"
              disabled={isRunning}
              onClick={() => void submitPrompt(starter.prompt)}
            >
              <SquareTerminal size={16} />
              <span>{starter.label}</span>
            </button>
          ))}
        </div>

        {timings.length ? <TimingTable rows={timings} /> : null}

        <section className="transcript" aria-label="Chat transcript">
          {visibleMessages.map((message, index) => (
            <ChatBubble message={message} key={`${message.role}-${index}`} />
          ))}
          {!visibleMessages.length && <div className="empty-state">Ask a source-backed question to start a run.</div>}
          <div ref={endRef} />
        </section>

        {toolCalls.length ? (
          <section className="detail-stack" aria-label="Tool calls">
            {toolCalls.map((toolCall, index) => (
              <ToolCallPanel toolCall={toolCall} key={toolCall.id || index} />
            ))}
          </section>
        ) : null}

        {toolPayloads.length ? (
          <section className="detail-stack" aria-label="Tool results">
            {toolPayloads.map((payload, index) => (
              <ToolResultPanel payload={payload} onPreviewTrace={previewTrace} key={`${payload.run_id || "pre"}-${index}`} />
            ))}
          </section>
        ) : null}

        {tracePreview ? <TracePreviewPanel preview={tracePreview} onClose={() => setTracePreview(null)} /> : null}

        <form className="prompt-form" onSubmit={handleSubmit}>
          <label htmlFor="prompt">Ask a source-backed question</label>
          <div className="prompt-row">
            <textarea
              id="prompt"
              value={prompt}
              disabled={isRunning}
              onChange={(event) => setPrompt(event.target.value)}
              rows={2}
            />
            <button type="submit" disabled={isRunning || !prompt.trim()} aria-label="Send prompt">
              <Send size={18} />
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}

function TimingTable({ rows }: { rows: TimingRow[] }) {
  return (
    <section className="timing-panel" aria-label="Request timers">
      <h3>Request timers</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Phase</th>
              <th>Status</th>
              <th>Seconds</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.phase}-${row.status}-${row.seconds}`}>
                <td>{row.phase}</td>
                <td>{row.status}</td>
                <td>{row.seconds.toFixed(1)}</td>
                <td>{row.details || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const content = message.content || "";
  return (
    <article className={`chat-bubble role-${message.role}`}>
      <div className="bubble-role">{message.role}</div>
      {message.role === "assistant" ? (
        <MarkdownBlock markdown={content} />
      ) : (
        <p>{content}</p>
      )}
    </article>
  );
}

function ToolCallPanel({ toolCall }: { toolCall: ToolCall }) {
  const functionPayload = toolCall.function || {};
  const args = parseJsonMaybe(functionPayload.arguments || "");
  return (
    <details className="detail-panel" open>
      <summary>Tool call: {functionPayload.name || "unknown"} ({toolCall.id || "missing-id"})</summary>
      {args ? <JsonBlock value={args} /> : <pre>{functionPayload.arguments}</pre>}
    </details>
  );
}

function ToolResultPanel({
  payload,
  onPreviewTrace,
}: {
  payload: ToolPayload;
  onPreviewTrace: (file: FileRef) => void;
}) {
  const reasoningTraces = payload.traces.filter(isReasoningTrace);
  const diagnosticTraces = payload.traces.filter((file) => !isReasoningTrace(file));

  return (
    <details className="detail-panel" open>
      <summary>Tool result: {payload.status} ({payload.run_id || "pre-run"})</summary>
      {payload.report_markdown ? <MarkdownBlock markdown={payload.report_markdown} /> : null}
      {payload.needs_clarification ? <div className="warning-box">{payload.needs_clarification.question}</div> : null}
      {payload.error ? <div className="error-box">{payload.error}</div> : null}
      {payload.artifacts.length ? <FileList title="Artifacts" files={payload.artifacts} /> : null}
      {reasoningTraces.length ? (
        <TraceList title="Model reasoning traces" files={reasoningTraces} onPreviewTrace={onPreviewTrace} />
      ) : null}
      {diagnosticTraces.length ? (
        <TraceList title="Trace files" files={diagnosticTraces} onPreviewTrace={onPreviewTrace} />
      ) : null}
    </details>
  );
}

function FileList({ title, files }: { title: string; files: FileRef[] }) {
  return (
    <div className="file-group">
      <h4>{title}</h4>
      <div className="file-list">
        {files.map((file) => (
          <div className="file-row" key={file.id}>
            {file.mime_type.startsWith("image/") ? (
              <img src={backendUrl(file.url)} alt={file.name} />
            ) : null}
            <a href={backendUrl(file.url)} target="_blank" rel="noreferrer">
              <Download size={15} />
              <span>{file.name}</span>
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

function TraceList({
  title,
  files,
  onPreviewTrace,
}: {
  title: string;
  files: FileRef[];
  onPreviewTrace: (file: FileRef) => void;
}) {
  return (
    <div className="file-group">
      <h4>{title}</h4>
      <div className="file-list">
        {files.map((file) => (
          <div className="file-row" key={file.id}>
            <button type="button" onClick={() => onPreviewTrace(file)}>
              Preview
            </button>
            <a href={backendUrl(file.url)} target="_blank" rel="noreferrer">
              {file.name}
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}

function TracePreviewPanel({
  preview,
  onClose,
}: {
  preview: TracePreview;
  onClose: () => void;
}) {
  return (
    <section className="trace-preview">
      <header>
        <h3>{preview.file.name}</h3>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </header>
      {preview.parsed ? <JsonBlock value={preview.parsed} /> : <pre>{preview.text}</pre>}
    </section>
  );
}

function MarkdownBlock({ markdown }: { markdown: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

function isVisibleMessage(message: ChatMessage) {
  if (!["user", "assistant"].includes(message.role)) {
    return false;
  }
  return !(message.role === "assistant" && message.tool_calls?.length && !message.content);
}

function collectToolCalls(messages: ChatMessage[]) {
  return messages.flatMap((message) => (message.role === "assistant" ? message.tool_calls || [] : []));
}

function collectToolPayloads(messages: ChatMessage[]) {
  return messages.flatMap((message) => {
    if (message.role !== "tool" || typeof message.content !== "string") {
      return [];
    }
    try {
      return [JSON.parse(message.content) as ToolPayload];
    } catch {
      return [];
    }
  });
}

function isReasoningTrace(file: FileRef) {
  const name = file.name.toLowerCase();
  return name === "events.jsonl" || name === "worker_prompt.md";
}

function parseJsonMaybe(text: string): unknown | null {
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function redactTrace(text: string) {
  return text
    .replace(/(Authorization:\s*Bearer\s+)[^\s"']+/gi, "$1<redacted>")
    .replace(/(api[_-]?key["']?\s*[:=]\s*["']?)[^"'\s,}]+/gi, "$1<redacted>")
    .replace(/(token["']?\s*[:=]\s*["']?)[^"'\s,}]+/gi, "$1<redacted>")
    .replace(/(secret["']?\s*[:=]\s*["']?)[^"'\s,}]+/gi, "$1<redacted>")
    .replace(/(password["']?\s*[:=]\s*["']?)[^"'\s,}]+/gi, "$1<redacted>");
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function wait(milliseconds: number) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}
