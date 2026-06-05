from __future__ import annotations

from dci_poc.agents.chat_agent import ChatCompletionAgent
from dci_poc.config import load_app_config
from dci_poc.controllers.chat_controller import ChatController
from dci_poc.managers.tool_manager import ToolManager
from dci_poc.schemas import build_tool_schemas
from dci_poc.services.approved_sources import ApprovedSourceService
from dci_poc.services.artifact_service import ArtifactService
from dci_poc.services.docker_runner import DockerRunner
from dci_poc.services.openai_chat_client import OpenAIChatClient
from dci_poc.services.prompt_service import WorkerPromptService
from dci_poc.services.run_folder_service import RunFolderService


def build_chat_controller() -> tuple[ChatController, ApprovedSourceService]:
    config = load_app_config()
    approved_sources = ApprovedSourceService(config)
    tool_schemas = build_tool_schemas(approved_sources.approved_paths())
    chat_client = OpenAIChatClient(config)
    agent = ChatCompletionAgent(config, chat_client)
    tool_manager = ToolManager(
        approved_sources=approved_sources,
        run_folders=RunFolderService(config),
        prompt_service=WorkerPromptService(),
        runner=DockerRunner(config),
        artifact_service=ArtifactService(),
    )
    return ChatController(agent, tool_manager, tool_schemas), approved_sources
