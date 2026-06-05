from __future__ import annotations

from dci_poc.agents.chat_agent import ChatCompletionAgent
from dci_poc.constants import API_TOOL_AUTO_ANALYSIS, API_TOOL_DCI_SEARCH
from dci_poc.controllers.chat_controller import ChatController, visible_messages
from dci_poc.managers.tool_manager import ToolManager
from dci_poc.schemas import build_tool_schemas
from dci_poc.services.approved_sources import ApprovedSourceService
from dci_poc.services.artifact_service import ArtifactService
from dci_poc.services.prompt_service import WorkerPromptService
from dci_poc.services.run_folder_service import RunFolderService
from fakes import FakeChatClient, FakeRunner
from helpers import tool_call


def build_controller(app_config, fake_client: FakeChatClient, fake_runner: FakeRunner) -> ChatController:
    approved_sources = ApprovedSourceService(app_config)
    manager = ToolManager(
        approved_sources=approved_sources,
        run_folders=RunFolderService(app_config),
        prompt_service=WorkerPromptService(),
        runner=fake_runner,  # type: ignore[arg-type]
        artifact_service=ArtifactService(),
    )
    agent = ChatCompletionAgent(app_config, fake_client)
    return ChatController(agent, manager, build_tool_schemas(approved_sources.approved_paths()))


def test_controller_rejects_multiple_tool_calls_without_running_worker(app_config) -> None:
    fake_client = FakeChatClient(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(API_TOOL_DCI_SEARCH, {"question": "A", "source_paths": ["sample_sources/dnd5e_hp_reference.md"]}, "call_1"),
                    tool_call(API_TOOL_DCI_SEARCH, {"question": "B", "source_paths": ["sample_sources/dnd5e_hp_reference.md"]}, "call_2"),
                ],
            },
            {"role": "assistant", "content": "I can run only one tool call per turn."},
        ]
    )
    runner = FakeRunner("success")
    controller = build_controller(app_config, fake_client, runner)

    result = controller.handle_user_turn([], "Find A and B.")

    assert result.assistant_message["content"] == "I can run only one tool call per turn."
    assert runner.calls == []
    assert len(result.tool_envelopes) == 2
    assert all(envelope.status.value == "error" for envelope in result.tool_envelopes)
    assert fake_client.payloads[0]["tool_choice"] == "auto"
    assert fake_client.payloads[0]["parallel_tool_calls"] is False


def test_streamlit_chat_loop_with_fake_completions_clarifies_then_runs(app_config) -> None:
    fake_client = FakeChatClient(
        [
            {
                "role": "assistant",
                "content": "Do you want fixed/average HP or rolled HP for levels after 1?",
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        API_TOOL_AUTO_ANALYSIS,
                        {
                            "question": (
                                "Use fixed HP. Calculate HP for a level 11 dwarf paladin "
                                "with 17 constitution."
                            ),
                            "source_paths": ["sample_sources/dnd5e_hp_reference.md"],
                        },
                    )
                ],
            },
            {"role": "assistant", "content": "Using fixed HP, the level 11 total is 91 HP."},
        ]
    )
    runner = FakeRunner("auto_analysis_success", answer="Final: 91 HP (dnd5e_hp_reference.md: Section Paladin).")
    controller = build_controller(app_config, fake_client, runner)

    first = controller.handle_user_turn([], "Calculate HP for a level 11 dwarf paladin with 17 constitution.")
    second = controller.handle_user_turn(
        first.messages,
        "Use fixed HP. No extra ancestry HP options.",
    )

    assert "fixed/average" in first.assistant_message["content"]
    assert second.assistant_message["content"] == "Using fixed HP, the level 11 total is 91 HP."
    assert len(runner.calls) == 1
    assert second.tool_envelopes[0].status.value == "success"
    assert any(path.endswith("results.csv") for path in second.tool_envelopes[0].artifact_paths)
    assert all("tool_calls" not in message for message in visible_messages(second.messages))
