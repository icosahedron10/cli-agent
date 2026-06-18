from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import streamlit as st

from cli_agent.app_factory import build_chat_controller
from cli_agent.constants import UI_TOOL_LABELS
from cli_agent.controllers.chat_controller import decode_tool_message_content, visible_messages


STARTER_QUESTIONS = (
    {
        "key": "starter_source_search",
        "label": f"{UI_TOOL_LABELS['source_search']}: 0 HP combat rule",
        "prompt": (
            'Use source_search with source_paths ["5e PHB/chapters/10 - Chapter 9 - Combat.pdf"] '
            "to answer: what does the PHB say happens when a creature drops to 0 hit points? "
            "Include citations."
        ),
    },
    {
        "key": "starter_auto_analysis",
        "label": f"{UI_TOOL_LABELS['auto_analysis']}: equipment totals",
        "prompt": (
            'Use auto_analysis with source_paths ["5e PHB/chapters/05 - Chapter 5 - Equipment.pdf"] '
            "to calculate the total gp cost and total weight for this equipment loadout: chain mail, "
            "shield, longsword, and 2 handaxes. Include a short table and cite the source."
        ),
    },
)
TIMER_REFRESH_SECONDS = 0.5
AGGREGATE_TIMING_PHASES = {"tool execution", "Docker worker run", "Docker CLI subprocess"}
TRACE_MAX_CHARS = 300_000
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)(Authorization:\s*Bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
    re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
    re.compile(r"(?i)(secret[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
    re.compile(r"(?i)(password[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
)


def _tool_payloads(messages: list[dict]) -> list[dict]:
    payloads: list[dict] = []
    for message in messages:
        payload = decode_tool_message_content(message)
        if payload is not None:
            payloads.append(payload)
    return payloads


def _tool_calls(messages: list[dict]) -> list[dict]:
    calls: list[dict] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            if isinstance(tool_call, dict):
                calls.append(tool_call)
    return calls


def _render_tool_call(tool_call: dict) -> None:
    function = tool_call.get("function")
    if not isinstance(function, dict):
        function = {}

    name = function.get("name") or "unknown"
    call_id = tool_call.get("id") or "missing-id"
    with st.expander(f"Tool call: {name} ({call_id})", expanded=True):
        raw_arguments = function.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                st.code(raw_arguments, language="json")
            else:
                st.json(arguments)
            return

        st.json(tool_call)


def _render_artifact(path: Path) -> None:
    if path.suffix.lower() == ".csv" and path.exists():
        st.download_button(
            label=f"Download {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime="text/csv",
        )
        return
    if path.suffix.lower() == ".png" and path.exists():
        st.image(str(path), caption=path.name)
        return
    st.code(str(path), language=None)


def _render_tool_payload(payload: dict) -> None:
    run_id = payload.get("run_id") or "pre-run"
    status = payload.get("status", "unknown")
    with st.expander(f"Tool result: {status} ({run_id})", expanded=True):
        report = payload.get("report_markdown") or ""
        if report:
            st.markdown(report)

        needs = payload.get("needs_clarification")
        if isinstance(needs, dict):
            st.warning(needs.get("question", "Clarification is required."))

        error = payload.get("error")
        if error:
            st.error(error)

        artifact_paths = payload.get("artifact_paths") or []
        for artifact_path in artifact_paths:
            _render_artifact(Path(artifact_path))


def _messages_with_failed_turn(
    history: list[dict],
    user_content: str,
    error: Exception,
) -> list[dict]:
    return [
        *history,
        {"role": "user", "content": user_content},
        {
            "role": "assistant",
            "content": f"Backend error before the turn completed: {error}",
        },
    ]


def _record_progress_event(
    timing_state: dict[str, Any],
    timing_lock: threading.Lock,
    phase: str,
    event: str,
    data: dict[str, Any] | None = None,
) -> None:
    now = time.perf_counter()
    with timing_lock:
        active = timing_state["active"]
        completed = timing_state["completed"]
        if event == "duration":
            completed.append(
                {
                    "phase": phase,
                    "status": (data or {}).get("status", "done"),
                    "seconds": float((data or {}).get("seconds", 0.0)),
                    "details": (data or {}).get("details", ""),
                }
            )
            return
        if event == "start":
            active[phase] = now
            return
        if event != "end":
            return

        started_at = active.pop(phase, None)
        if started_at is None:
            return
        completed.append(
            {
                "phase": phase,
                "status": "done",
                "seconds": now - started_at,
                "details": "",
            }
        )


def _timing_rows(timing_state: dict[str, Any], timing_lock: threading.Lock) -> list[dict[str, Any]]:
    now = time.perf_counter()
    with timing_lock:
        rows = [dict(row) for row in timing_state["completed"]]
        rows.extend(
            {
                "phase": phase,
                "status": "running",
                "seconds": now - started_at,
            }
            for phase, started_at in timing_state["active"].items()
        )

    rows.sort(key=lambda row: row["seconds"], reverse=True)
    return rows


def _format_timing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Phase": row["phase"],
            "Status": row["status"],
            "Seconds": round(row["seconds"], 1),
            "Details": row.get("details", ""),
        }
        for row in rows
    ]


def _detail_timing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["phase"] not in AGGREGATE_TIMING_PHASES]


def _wrapper_timing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["phase"] in AGGREGATE_TIMING_PHASES]


def _slowest_detail_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    detail_rows = _detail_timing_rows(rows)
    return max(detail_rows or rows, key=lambda row: row["seconds"])


def _render_timing_panel(container, rows: list[dict[str, Any]], title: str) -> None:
    with container.container():
        st.subheader(title)
        if not rows:
            st.caption("Waiting for first event...")
            return

        slowest = _slowest_detail_row(rows)
        st.caption(
            f"Longest detailed phase so far: {slowest['phase']} "
            f"({slowest['seconds']:.1f}s, {slowest['status']})"
        )
        detail_rows = _detail_timing_rows(rows)
        if detail_rows:
            st.table(_format_timing_rows(detail_rows))
        else:
            st.caption("No detailed worker timing has been emitted yet.")

        wrapper_rows = _wrapper_timing_rows(rows)
        if wrapper_rows:
            st.caption("Wrapper phases")
            st.table(_format_timing_rows(wrapper_rows))


def _render_last_timing_summary() -> None:
    rows = st.session_state.get("last_timings") or []
    if not rows:
        return
    with st.expander("Request timers", expanded=True):
        slowest = _slowest_detail_row(rows)
        st.caption(f"Longest detailed phase: {slowest['phase']} ({slowest['seconds']:.1f}s)")
        detail_rows = _detail_timing_rows(rows)
        if detail_rows:
            st.table(_format_timing_rows(detail_rows))

        wrapper_rows = _wrapper_timing_rows(rows)
        if wrapper_rows:
            st.caption("Wrapper phases")
            st.table(_format_timing_rows(wrapper_rows))


def _render_full_trace(payload: dict, messages: list[dict]) -> None:
    run_id = payload.get("run_id") or "pre-run"
    with st.expander(f"Full trace ({run_id})", expanded=False):
        st.caption("Outer agent messages")
        st.json(_redact_data(messages))

        diagnostics = _read_worker_diagnostics(payload)
        if diagnostics:
            st.caption("Worker diagnostics")
            st.json(_redact_data(diagnostics))

        trace_paths = payload.get("trace_paths") or []
        if not trace_paths:
            st.caption("No worker trace files were reported for this run.")
            return

        st.caption("Worker trace files")
        selected_trace_path = st.selectbox(
            "Trace file",
            options=trace_paths,
            format_func=lambda value: _display_trace_path(Path(value)),
            key=f"trace_file_{run_id}",
        )
        _render_trace_file(Path(selected_trace_path))


def _read_worker_diagnostics(payload: dict) -> dict[str, Any] | None:
    for trace_path in payload.get("trace_paths") or []:
        path = Path(trace_path)
        if path.name != "worker_diagnostics.json":
            continue
        text = _safe_read_trace_text(path)
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _render_trace_file(path: Path) -> None:
    label = _display_trace_path(path)
    text = _safe_read_trace_text(path)
    st.caption(label)
    if text is None:
        st.warning("Trace file is unavailable or outside the workspace.")
        return
    if path.suffix == ".json":
        try:
            st.json(_redact_data(json.loads(text)))
        except json.JSONDecodeError:
            st.code(_redact_text(text), language="json")
        return
    if path.name == "events.jsonl":
        _render_copilot_event_summary(text)
    st.code(_redact_text(text), language=_trace_language(path))


def _render_copilot_event_summary(text: str) -> None:
    rows = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type not in {
            "user.message",
            "assistant.message",
            "tool.execution_start",
            "tool.execution_complete",
            "assistant.turn_start",
            "assistant.turn_end",
            "session.model_change",
        }:
            continue
        rows.append(
            {
                "timestamp": event.get("timestamp", ""),
                "type": event_type,
                "summary": _event_summary(event),
            }
        )
    if rows:
        st.caption("Parsed Copilot event timeline")
        st.table(rows[:200])


def _event_summary(event: dict[str, Any]) -> str:
    data = event.get("data")
    if not isinstance(data, dict):
        return ""
    if event.get("type") == "assistant.message":
        tool_requests = data.get("toolRequests") or []
        return f"assistant output, {len(tool_requests)} tool request(s)"
    if event.get("type") == "tool.execution_start":
        return f"{data.get('toolName', 'tool')} start"
    if event.get("type") == "tool.execution_complete":
        return f"tool complete success={data.get('success')}"
    if event.get("type") == "user.message":
        return "worker prompt"
    if event.get("type") == "session.model_change":
        return f"model={data.get('newModel')}"
    return ""


def _safe_read_trace_text(path: Path) -> str | None:
    try:
        resolved = path.resolve()
        workspace = Path.cwd().resolve()
        resolved.relative_to(workspace)
    except (OSError, ValueError):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    text = resolved.read_text(encoding="utf-8", errors="replace")
    if len(text) > TRACE_MAX_CHARS:
        return text[:TRACE_MAX_CHARS] + "\n\n[trace truncated in UI]"
    return text


def _display_trace_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _trace_language(path: Path) -> str | None:
    if path.suffix == ".jsonl":
        return "json"
    if path.suffix in {".json", ".yaml", ".yml"}:
        return path.suffix.removeprefix(".")
    if path.suffix in {".md", ".log"}:
        return path.suffix.removeprefix(".")
    return None


def _redact_data(value: Any) -> Any:
    return json.loads(_redact_text(json.dumps(value, default=str)))


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    return redacted


def _render_starter_questions() -> str | None:
    columns = st.columns(len(STARTER_QUESTIONS))
    for column, starter in zip(columns, STARTER_QUESTIONS, strict=True):
        if column.button(
            starter["label"],
            key=starter["key"],
            help=starter["prompt"],
            use_container_width=True,
        ):
            return starter["prompt"]
    return None


def _run_controller_turn(
    history: list[dict],
    user_content: str,
    timing_state: dict[str, Any],
    timing_lock: threading.Lock,
    result_holder: dict[str, Any],
) -> None:
    def progress_callback(phase: str, event: str, data: dict[str, Any] | None = None) -> None:
        _record_progress_event(timing_state, timing_lock, phase, event, data)

    try:
        result_holder["result"] = controller.handle_user_turn(
            history,
            user_content,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        result_holder["error"] = exc


def _submit_prompt(history: list[dict], user_content: str) -> None:
    with st.chat_message("user"):
        st.markdown(user_content)

    timing_state = {"completed": [], "active": {}}
    timing_lock = threading.Lock()
    result_holder: dict[str, Any] = {}
    timing_container = st.empty()
    st.session_state.last_timings = []

    worker = threading.Thread(
        target=_run_controller_turn,
        args=(history, user_content, timing_state, timing_lock, result_holder),
        daemon=True,
    )
    worker.start()
    while worker.is_alive():
        _render_timing_panel(timing_container, _timing_rows(timing_state, timing_lock), "Live request timers")
        time.sleep(TIMER_REFRESH_SECONDS)
    worker.join()

    final_rows = _timing_rows(timing_state, timing_lock)
    _render_timing_panel(timing_container, final_rows, "Live request timers")
    st.session_state.last_timings = final_rows

    if "error" in result_holder:
        exc = result_holder["error"]
        st.session_state.messages = _messages_with_failed_turn(history, user_content, exc)
        st.error(f"Backend error before the turn completed: {exc}")
        return

    result = result_holder["result"]
    st.session_state.messages = result.messages
    st.rerun()


st.set_page_config(page_title="CLI Source Tool", layout="wide")
st.title("CLI Source and Auto Analysis")


@st.cache_resource
def _load_controller():
    return build_chat_controller()


controller, approved_sources = _load_controller()

with st.sidebar:
    st.subheader("Approved Sources")
    for source in approved_sources.all_sources():
        st.caption(source.label)
        st.code(source.path, language=None)

if "messages" not in st.session_state:
    st.session_state.messages = []

starter_prompt = _render_starter_questions()

for message in visible_messages(st.session_state.messages):
    if message.get("role") == "system":
        continue
    content = message.get("content") or ""
    with st.chat_message(message["role"]):
        st.markdown(content)

for tool_call in _tool_calls(st.session_state.messages):
    _render_tool_call(tool_call)

for tool_payload in _tool_payloads(st.session_state.messages):
    _render_tool_payload(tool_payload)

for tool_payload in _tool_payloads(st.session_state.messages):
    _render_full_trace(tool_payload, st.session_state.messages)

_render_last_timing_summary()

prompt = st.chat_input("Ask a source-backed question")
submitted_prompt = starter_prompt or prompt
if submitted_prompt:
    _submit_prompt(st.session_state.messages, submitted_prompt)
