from dataclasses import dataclass
from typing import Literal


@dataclass
class OpenClawConfig:
    agent_name: str = "StudentLifeClaw"
    version: str = "0.1.0"
    max_tool_iterations: int = 10
    timeout_seconds: int = 60
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    mock_mode: bool = False
