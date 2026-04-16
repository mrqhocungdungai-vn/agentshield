#!/usr/bin/env python3
"""
AgentShield Config TUI
======================
Terminal UI for configuring AgentShield on the server.
Launch: agentshield-config

All changes are in-memory until "Save & Exit" is pressed.
Saves atomically to ~/.hermes/agentshield.yaml.

This tool runs only on the server (SSH session).
No configuration is possible via Telegram or any chat channel.
"""

import os
import sys
from pathlib import Path
from copy import deepcopy

try:
    import yaml
except ImportError:
    print("PyYAML is required. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.screen import Screen
    from textual.widgets import (
        Button, Footer, Header, Input, Label, ListItem,
        ListView, Static, TextArea
    )
except ImportError:
    print("Textual is required. Run: pip install textual", file=sys.stderr)
    sys.exit(1)


# ── Config path ──────────────────────────────────────────────────────────────

def _config_path() -> Path:
    return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))) / "agentshield.yaml"


def _load_config() -> dict:
    path = _config_path()
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cfg = data.get("agentshield", data)
            # Normalise to flat config structure (v1.0.0 format)
            return {
                "enabled": cfg.get("enabled", True),
                "rate_limit": cfg.get("rate_limit", {
                    "messages_per_minute": 10,
                    "messages_per_day": 200,
                }),
                "allow": cfg.get("allow", ["chat"]),
                "deny": cfg.get("deny", ["command:*", "skill:*", "system:*", "terminal"]),
                "messages": cfg.get("messages", {
                    "rate_limit_minute": "Tôi đang xử lý nhiều yêu cầu — bạn vui lòng thử lại sau giây lát nhé 😊",
                    "rate_limit_day": "Bạn đã đạt giới hạn tin nhắn hôm nay. Hẹn gặp lại bạn vào ngày mai!",
                    "action_denied": "Tính năng này chưa khả dụng trong cuộc trò chuyện này. Vui lòng liên hệ bộ phận hỗ trợ 😊",
                }),
                "logging": cfg.get("logging", {"conversations": True}),
            }
        except Exception as e:
            print(f"[agentshield-config] Error loading config: {e}", file=sys.stderr)
    # Default config
    return {
        "enabled": True,
        "rate_limit": {"messages_per_minute": 10, "messages_per_day": 200},
        "allow": ["chat"],
        "deny": ["command:*", "skill:*", "system:*", "terminal"],
        "messages": {
            "rate_limit_minute": "Tôi đang xử lý nhiều yêu cầu — bạn vui lòng thử lại sau giây lát nhé 😊",
            "rate_limit_day": "Bạn đã đạt giới hạn tin nhắn hôm nay. Hẹn gặp lại bạn vào ngày mai!",
            "action_denied": "Tính năng này chưa khả dụng trong cuộc trò chuyện này. Vui lòng liên hệ bộ phận hỗ trợ 😊",
        },
        "logging": {"conversations": True},
    }


def _save_config(cfg: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump({"agentshield": cfg}, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    tmp.replace(path)


# ── Presets ──────────────────────────────────────────────────────────────────

PRESETS = {
    "Chat only": {
        "allow": ["chat"],
        "deny": ["command:*", "skill:*", "system:*", "terminal"],
    },
    "Chat + Commands": {
        "allow": ["chat", "command:*"],
        "deny": ["skill:*", "system:*", "terminal"],
    },
    "Unrestricted": {
        "allow": [],
        "deny": [],
    },
}


# ── Screens ──────────────────────────────────────────────────────────────────

class RateLimitScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config["rate_limit"]  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        yield Label("Rate Limits", id="screen-title")
        yield Label("Messages per minute:")
        yield Input(value=str(cfg.get("messages_per_minute", 10)), id="per-minute", placeholder="e.g. 10")
        yield Label("Messages per day:")
        yield Input(value=str(cfg.get("messages_per_day", 200)), id="per-day", placeholder="e.g. 200")
        yield Button("Save", id="save-rate", variant="primary")
        yield Button("Back", id="back-rate", variant="default")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-rate":
            try:
                per_min = int(self.query_one("#per-minute", Input).value)
                per_day = int(self.query_one("#per-day", Input).value)
                self.app.config["rate_limit"] = {  # type: ignore[attr-defined]
                    "messages_per_minute": per_min,
                    "messages_per_day": per_day,
                }
                self.notify("Rate limits saved ✓")
            except ValueError:
                self.notify("Error: values must be integers", severity="error")
        elif event.button.id == "back-rate":
            self.app.pop_screen()


class AllowDenyScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        cfg = self.app.config  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        yield Label("Allow / Deny Rules", id="screen-title")

        yield Label("── ALLOW ────────────────────────────────")
        for item in cfg["allow"]:
            yield Horizontal(
                Static(f"  {item}", classes="rule-item"),
                Button("Delete", id=f"del-allow-{item}", variant="error", classes="del-btn"),
            )
        yield Horizontal(
            Input(placeholder="Add allow pattern (e.g. chat)", id="add-allow-input"),
            Button("Add", id="add-allow-btn", variant="success"),
        )

        yield Label("── DENY ─────────────────────────────────")
        for item in cfg["deny"]:
            yield Horizontal(
                Static(f"  {item}", classes="rule-item"),
                Button("Delete", id=f"del-deny-{item}", variant="error", classes="del-btn"),
            )
        yield Horizontal(
            Input(placeholder="Add deny pattern (e.g. command:*)", id="add-deny-input"),
            Button("Add", id="add-deny-btn", variant="success"),
        )

        yield Label("── PRESETS ──────────────────────────────")
        for preset_name in PRESETS:
            yield Button(preset_name, id=f"preset-{preset_name}", variant="warning")

        yield Button("Back", id="back-rules", variant="default")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        cfg = self.app.config  # type: ignore[attr-defined]

        if bid.startswith("del-allow-"):
            item = bid[len("del-allow-"):]
            cfg["allow"] = [x for x in cfg["allow"] if x != item]
            self.notify(f"Removed allow: {item}")
            self.app.pop_screen()
            self.app.push_screen(AllowDenyScreen())

        elif bid.startswith("del-deny-"):
            item = bid[len("del-deny-"):]
            cfg["deny"] = [x for x in cfg["deny"] if x != item]
            self.notify(f"Removed deny: {item}")
            self.app.pop_screen()
            self.app.push_screen(AllowDenyScreen())

        elif bid == "add-allow-btn":
            val = self.query_one("#add-allow-input", Input).value.strip()
            if val and val not in cfg["allow"]:
                cfg["allow"].append(val)
                self.notify(f"Added allow: {val}")
                self.app.pop_screen()
                self.app.push_screen(AllowDenyScreen())

        elif bid == "add-deny-btn":
            val = self.query_one("#add-deny-input", Input).value.strip()
            if val and val not in cfg["deny"]:
                cfg["deny"].append(val)
                self.notify(f"Added deny: {val}")
                self.app.pop_screen()
                self.app.push_screen(AllowDenyScreen())

        elif bid.startswith("preset-"):
            preset_name = bid[len("preset-"):]
            preset = PRESETS[preset_name]
            cfg["allow"] = list(preset["allow"])
            cfg["deny"] = list(preset["deny"])
            self.notify(f"Applied preset: {preset_name}")
            self.app.pop_screen()
            self.app.push_screen(AllowDenyScreen())

        elif bid == "back-rules":
            self.app.pop_screen()


class MessagesScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        msgs = self.app.config["messages"]  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        yield Label("Response Messages", id="screen-title")
        yield Label("Rate limit (minute):")
        yield TextArea(msgs.get("rate_limit_minute", ""), id="msg-rate-min")
        yield Label("Rate limit (day):")
        yield TextArea(msgs.get("rate_limit_day", ""), id="msg-rate-day")
        yield Label("Action denied:")
        yield TextArea(msgs.get("action_denied", ""), id="msg-denied")
        yield Button("Save", id="save-msgs", variant="primary")
        yield Button("Back", id="back-msgs", variant="default")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-msgs":
            self.app.config["messages"] = {  # type: ignore[attr-defined]
                "rate_limit_minute": self.query_one("#msg-rate-min", TextArea).text,
                "rate_limit_day": self.query_one("#msg-rate-day", TextArea).text,
                "action_denied": self.query_one("#msg-denied", TextArea).text,
            }
            self.notify("Messages saved ✓")
        elif event.button.id == "back-msgs":
            self.app.pop_screen()


class MainScreen(Screen):
    BINDINGS = [Binding("q", "quit_app", "Quit")]

    def compose(self) -> ComposeResult:
        enabled = self.app.config.get("enabled", True)  # type: ignore[attr-defined]
        yield Header(show_clock=False)
        yield Label("AgentShield Configuration", id="screen-title")
        yield Label("One role. Maximum security.", id="subtitle")
        yield Static("")
        yield Button("Rate Limits", id="nav-rate", variant="default")
        yield Button("Allow / Deny Rules", id="nav-rules", variant="default")
        yield Button("Response Messages", id="nav-messages", variant="default")
        yield Button(
            f"Toggle AgentShield: {'✅ Enabled' if enabled else '❌ Disabled'}",
            id="toggle-enabled", variant="warning"
        )
        yield Static("")
        yield Button("Save & Exit", id="save-exit", variant="primary")
        yield Button("Exit without saving", id="exit-nosave", variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "nav-rate":
            self.app.push_screen(RateLimitScreen())
        elif bid == "nav-rules":
            self.app.push_screen(AllowDenyScreen())
        elif bid == "nav-messages":
            self.app.push_screen(MessagesScreen())
        elif bid == "toggle-enabled":
            self.app.config["enabled"] = not self.app.config.get("enabled", True)  # type: ignore[attr-defined]
            self.app.pop_screen()
            self.app.push_screen(MainScreen())
        elif bid == "save-exit":
            try:
                _save_config(self.app.config)  # type: ignore[attr-defined]
                self.notify(f"Saved to {_config_path()} ✓")
                self.app.exit(0)
            except Exception as e:
                self.notify(f"Save failed: {e}", severity="error")
        elif bid == "exit-nosave":
            self.app.exit(0)

    def action_quit_app(self) -> None:
        self.app.exit(0)


# ── App ───────────────────────────────────────────────────────────────────────

class AgentShieldConfig(App):
    TITLE = "AgentShield Config"
    SUB_TITLE = "Server-side configuration only"
    CSS = """
    #screen-title {
        color: $accent;
        text-style: bold;
        margin: 1 0;
        padding: 0 2;
    }
    #subtitle {
        color: $text-muted;
        padding: 0 2;
        margin-bottom: 1;
    }
    Button {
        margin: 0 2 1 2;
        width: 40;
    }
    Label {
        padding: 0 2;
    }
    Input, TextArea {
        margin: 0 2 1 2;
    }
    .rule-item {
        width: 1fr;
        padding: 0 2;
    }
    .del-btn {
        width: 8;
        margin: 0 1;
    }
    """

    def __init__(self):
        super().__init__()
        self.config = _load_config()

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


def main():
    app = AgentShieldConfig()
    app.run()


if __name__ == "__main__":
    main()
