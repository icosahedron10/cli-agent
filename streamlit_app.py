from __future__ import annotations

from pathlib import Path

import streamlit as st

from cli_agent.app_factory import build_chat_controller
from cli_agent.constants import UI_TOOL_LABELS
from cli_agent.controllers.chat_controller import decode_tool_message_content, visible_messages


def _tool_payloads(messages: list[dict]) -> list[dict]:
    payloads: list[dict] = []
    for message in messages:
        payload = decode_tool_message_content(message)
        if payload is not None:
            payloads.append(payload)
    return payloads


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
    with st.expander(f"Tool result: {status} ({run_id})", expanded=False):
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

for message in visible_messages(st.session_state.messages):
    if message.get("role") == "system":
        continue
    content = message.get("content") or ""
    with st.chat_message(message["role"]):
        st.markdown(content)

for tool_payload in _tool_payloads(st.session_state.messages):
    _render_tool_payload(tool_payload)

prompt = st.chat_input("Ask a source-backed question")
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        result = controller.handle_user_turn(st.session_state.messages, prompt)
    except Exception as exc:
        st.session_state.messages = _messages_with_failed_turn(st.session_state.messages, prompt, exc)
        st.error(f"Backend error before the turn completed: {exc}")
    else:
        st.session_state.messages = result.messages
        st.rerun()
