"""
Tests for the role-based access control engine.
"""

import pytest
from gateway.config import Config, TelegramConfig, AgentConfig, RoleConfig, LoggingConfig
from gateway.roles import RoleEngine


def make_config():
    return Config(
        telegram=TelegramConfig(bot_token="test", owner_chat_id="1000"),
        agent=AgentConfig(),
        roles={
            "admin": RoleConfig(
                chat_ids=["2000"],
                allow=["*"],
                deny=["system:reset"],
            ),
            "user": RoleConfig(
                allow=["chat", "help"],
                deny=[],
            ),
            "guest": RoleConfig(
                allow=["help"],
                deny=[],
            ),
        },
        default_role="guest",
        logging=LoggingConfig(),
    )


def test_owner_always_allowed():
    engine = RoleEngine(make_config())
    assert engine.is_allowed("1000", "system:reset") is True
    assert engine.is_allowed("1000", "memory:delete_all") is True


def test_admin_allowed_except_denied():
    engine = RoleEngine(make_config())
    assert engine.is_allowed("2000", "chat") is True
    assert engine.is_allowed("2000", "system:reset") is False


def test_user_allowed():
    engine = RoleEngine(make_config())
    engine.assign_role("3000", "user")
    assert engine.is_allowed("3000", "chat") is True
    assert engine.is_allowed("3000", "help") is True
    assert engine.is_allowed("3000", "skill:delete") is False


def test_guest_default_role():
    engine = RoleEngine(make_config())
    # Unknown user -> guest
    assert engine.get_role("9999") == "guest"
    assert engine.is_allowed("9999", "help") is True
    assert engine.is_allowed("9999", "chat") is False


def test_dynamic_role_assignment():
    engine = RoleEngine(make_config())
    engine.assign_role("5000", "user")
    assert engine.get_role("5000") == "user"
    engine.assign_role("5000", "admin")
    assert engine.get_role("5000") == "admin"
