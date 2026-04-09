"""
Configuration loader for AgentShield.
Reads config.yaml and returns typed config objects.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml


@dataclass
class RateLimitConfig:
    messages_per_minute: int = 30
    messages_per_day: int = 500


@dataclass
class RoleConfig:
    allow: List[str] = field(default_factory=lambda: ["*"])
    deny: List[str] = field(default_factory=list)
    chat_ids: List[str] = field(default_factory=list)
    rate_limit: Optional[RateLimitConfig] = None


@dataclass
class AgentConfig:
    type: str = "hermes"
    path: str = "~/.hermes"
    command: Optional[str] = None


@dataclass
class TelegramConfig:
    bot_token: str = ""
    owner_chat_id: str = ""


@dataclass
class LoggingConfig:
    level: str = "info"
    file: str = "~/.agentshield/logs/gateway.log"
    log_conversations: bool = True


@dataclass
class Config:
    telegram: TelegramConfig
    agent: AgentConfig
    roles: Dict[str, RoleConfig]
    default_role: str = "guest"
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: Path) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)

    telegram = TelegramConfig(**raw.get("telegram", {}))
    agent = AgentConfig(**raw.get("agent", {}))
    logging_cfg = LoggingConfig(**raw.get("logging", {}))

    roles = {}
    for role_name, role_data in raw.get("roles", {}).items():
        rl_data = role_data.pop("rate_limit", None)
        rate_limit = RateLimitConfig(**rl_data) if rl_data else None
        roles[role_name] = RoleConfig(**role_data, rate_limit=rate_limit)

    return Config(
        telegram=telegram,
        agent=agent,
        roles=roles,
        default_role=raw.get("default_role", "guest"),
        logging=logging_cfg,
    )
