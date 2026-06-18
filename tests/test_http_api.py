from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cli_agent.agents.chat_agent import ChatCompletionAgent
from cli_agent.constants import API_TOOL_AUTO_ANALYSIS
from cli_agent.controllers.chat_controller import ChatController
from cli_agent.http_api import (
    ApiState,
    CliAgentRequestHandler,
    _encode_file_id,
)
from cli_agent.managers.tool_manager import ToolManager
from cli_agent.schemas import build_tool_schemas
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.services.artifact_service import ArtifactService
from cli_agent.services.prompt_service import WorkerPromptService
from cli_agent.services.run_folder_service import RunFolderService
from fakes import FakeChatClient, FakeRunner
from helpers import tool_call


def build_state(app_settings, fake_client: FakeChatClient, fake_runner: FakeRunner) -> ApiState:
    approved_sources = ApprovedSourceService(app_settings)
    manager = ToolManager(
        approved_sources=approved_sources,
        run_folders=RunFolderService(app_settings),
        prompt_service=WorkerPromptService(),
        runner=fake_runner,  # type: ignore[arg-type]
        artifact_service=ArtifactService(),
    )
    agent = ChatCompletionAgent(app_settings, fake_client)
    controller = ChatController(agent, manager, build_tool_schemas(approved_sources.approved_paths()))
    return ApiState(
        settings=app_settings,
        controller=controller,
        approved_sources=approved_sources,
        cors_origin="http://frontend.test",
    )


@contextmanager
def api_server(state: ApiState):
    server = ThreadingHTTPServer(("127.0.0.1", 0), CliAgentRequestHandler)
    server.api_state = state  # type: ignore[attr-defined]
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2.0)
        server.server_close()


def get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_complete(base_url: str, request_id: str) -> dict[str, Any]:
    deadline = time.time() + 5
    while time.time() < deadline:
        payload = get_json(f"{base_url}/runs/{request_id}/events")
        if payload["status"] != "running":
            return payload
        time.sleep(0.05)
    raise AssertionError("chat job did not complete")


def test_sources_endpoint_returns_approved_sources(app_settings) -> None:
    state = build_state(app_settings, FakeChatClient([]), FakeRunner())

    with api_server(state) as base_url:
        payload = get_json(f"{base_url}/sources")

    assert payload["sources"] == [
        {
            "path": "sample_sources/dnd5e_hp_reference.md",
            "label": "HP Reference",
            "description": "Demo HP source",
            "size_bytes": (app_settings.repo_root / "sample_sources/dnd5e_hp_reference.md").stat().st_size,
        }
    ]


def test_chat_endpoint_returns_sanitized_completed_result(app_settings) -> None:
    fake_client = FakeChatClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        API_TOOL_AUTO_ANALYSIS,
                        {
                            "question": "Use fixed HP. Calculate HP for a level 11 paladin.",
                            "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
                        },
                    )
                ],
            },
            {"role": "assistant", "content": "The total is 91 HP."},
        ]
    )
    state = build_state(app_settings, fake_client, FakeRunner("auto_analysis_success"))

    with api_server(state) as base_url:
        started = post_json(f"{base_url}/chat", {"messages": [], "prompt": "Calculate HP."})
        completed = wait_for_complete(base_url, started["request_id"])

    assert completed["status"] == "complete"
    result = completed["result"]
    assert result["assistant_message"]["content"] == "The total is 91 HP."
    assert result["tool_envelopes"][0]["artifact_paths"] == []
    assert result["tool_envelopes"][0]["artifacts"][0]["name"] == "results.csv"
    assert str(app_settings.runs_root) not in json.dumps(result)
    tool_messages = [message for message in result["messages"] if message["role"] == "tool"]
    assert tool_messages
    decoded_tool_content = json.loads(tool_messages[0]["content"])
    assert decoded_tool_content["artifacts"][0]["url"].startswith("/artifacts/")


def test_chat_jobs_evict_old_completed_entries(app_settings) -> None:
    capped_settings = replace(app_settings, max_api_jobs=2)
    fake_client = FakeChatClient(
        [
            {"role": "assistant", "content": "Done 1."},
            {"role": "assistant", "content": "Done 2."},
            {"role": "assistant", "content": "Done 3."},
        ]
    )
    state = build_state(capped_settings, fake_client, FakeRunner())

    with api_server(state) as base_url:
        started = []
        completed = []
        for index in range(3):
            started.append(post_json(f"{base_url}/chat", {"messages": [], "prompt": f"Prompt {index}"}))
            completed.append(wait_for_complete(base_url, started[-1]["request_id"]))
        with pytest.raises(HTTPError) as exc_info:
            get_json(f"{base_url}/runs/{started[0]['request_id']}/events")
        newest = get_json(f"{base_url}/runs/{started[-1]['request_id']}/events")

    assert [item["status"] for item in completed] == ["complete", "complete", "complete"]
    assert exc_info.value.code == 404
    assert newest["status"] == "complete"
    assert len(state.jobs) == 2


def test_artifact_route_serves_validated_file(app_settings) -> None:
    fake_client = FakeChatClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        API_TOOL_AUTO_ANALYSIS,
                        {
                            "question": "Use fixed HP. Calculate HP for a level 11 paladin.",
                            "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
                        },
                    )
                ],
            },
            {"role": "assistant", "content": "Done."},
        ]
    )
    state = build_state(app_settings, fake_client, FakeRunner("auto_analysis_success"))

    with api_server(state) as base_url:
        started = post_json(f"{base_url}/chat", {"messages": [], "prompt": "Calculate HP."})
        completed = wait_for_complete(base_url, started["request_id"])
        artifact = completed["result"]["tool_envelopes"][0]["artifacts"][0]
        with urlopen(f"{base_url}{artifact['url']}", timeout=5) as response:
            body = response.read().decode("utf-8")
            content_type = response.headers["Content-Type"]

    assert "level,hp" in body
    assert content_type.startswith("text/csv")


def test_artifact_route_rejects_path_escape(app_settings) -> None:
    run_id = "manual-run"
    run_root = app_settings.runs_root / run_id
    run_root.mkdir(parents=True)
    state = build_state(app_settings, FakeChatClient([]), FakeRunner())
    escape_id = _encode_file_id("../settings/approved_sources.json")

    with api_server(state) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base_url}/artifacts/{run_id}/{escape_id}", timeout=5)

    assert exc_info.value.code == 403


def test_artifact_route_rejects_encoded_run_id_escape(app_settings) -> None:
    outside_run_root = app_settings.runs_root.parent / "escaped-run"
    outside_run_root.mkdir(parents=True)
    (outside_run_root / "secret.txt").write_text("private", encoding="utf-8")
    state = build_state(app_settings, FakeChatClient([]), FakeRunner())
    escape_id = _encode_file_id("secret.txt")

    with api_server(state) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{base_url}/artifacts/..%2Fescaped-run/{escape_id}", timeout=5)

    assert exc_info.value.code == 403


def test_chat_endpoint_rejects_bad_request(app_settings) -> None:
    state = build_state(app_settings, FakeChatClient([]), FakeRunner())

    with api_server(state) as base_url:
        with pytest.raises(HTTPError) as exc_info:
            post_json(f"{base_url}/chat", {"messages": "bad", "prompt": ""})

    assert exc_info.value.code == 400
