from __future__ import annotations

from cli_agent.agents.chat_agent import ChatCompletionAgent
from cli_agent.models import AppSettings
from cli_agent.settings import load_app_settings
from cli_agent.controllers.chat_controller import ChatController
from cli_agent.managers.tool_manager import ToolManager
from cli_agent.schemas import build_tool_schemas
from cli_agent.services.approved_sources import ApprovedSourceService
from cli_agent.services.artifact_service import ArtifactService
from cli_agent.services.docker_runner import DockerRunner
from cli_agent.services.openai_chat_client import OpenAIChatClient
from cli_agent.services.prompt_service import WorkerPromptService
from cli_agent.services.run_folder_service import RunFolderService
from cli_agent.subagent import Subagent


def build_chat_controller() -> tuple[ChatController, ApprovedSourceService]:
    settings = load_app_settings()
    approved_sources = ApprovedSourceService(settings)
    tool_schemas = build_tool_schemas(
        approved_sources.approved_paths(),
        max_sources_per_run=settings.max_sources_per_run,
    )
    chat_client = OpenAIChatClient(settings)
    agent = ChatCompletionAgent(settings, chat_client)
    tool_manager = build_tool_manager(settings, approved_sources)
    return ChatController(agent, tool_manager, tool_schemas), approved_sources


def build_tool_manager(
    settings: AppSettings,
    approved_sources: ApprovedSourceService | None = None,
) -> ToolManager:
    source_service = approved_sources or ApprovedSourceService(settings)
    tool_manager = ToolManager(
        approved_sources=source_service,
        run_folders=RunFolderService(settings),
        prompt_service=WorkerPromptService(),
        runner=DockerRunner(settings),
        artifact_service=ArtifactService(),
    )
    return tool_manager


def build_subagent(
    settings: AppSettings,
    approved_sources: ApprovedSourceService | None = None,
) -> Subagent:
    return Subagent(build_tool_manager(settings, approved_sources))
