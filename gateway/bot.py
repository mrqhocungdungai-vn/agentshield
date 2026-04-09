"""
Telegram bot for AgentShield Phase 1 gateway.
Receives messages, checks permissions, forwards to agent.

Requires: python-telegram-bot>=20
"""

from __future__ import annotations
import logging
import subprocess
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from gateway.config import Config
from gateway.roles import RoleEngine

logger = logging.getLogger(__name__)


class AgentShieldBot:
    def __init__(self, config: Config):
        self.config = config
        self.roles = RoleEngine(config)

    async def run(self):
        app = (
            Application.builder()
            .token(self.config.telegram.bot_token)
            .build()
        )

        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("whoami", self._handle_whoami))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        logger.info("AgentShield gateway starting...")
        await app.run_polling()

    async def _handle_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        role = self.roles.get_role(chat_id)
        await update.message.reply_text(
            f"👋 Welcome to this AI agent, powered by AgentShield.\n"
            f"Your access level: {role}\n"
            f"Type /help to see what you can do."
        )

    async def _handle_whoami(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        role = self.roles.get_role(chat_id)
        await update.message.reply_text(f"Your role: **{role}**")

    async def _handle_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        if not self.roles.is_allowed(chat_id, "help"):
            await update.message.reply_text("❌ Access denied.")
            return
        await update.message.reply_text(
            "Just send me a message and I will help you.\n"
            "Commands: /start /whoami /help"
        )

    async def _handle_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        text = update.message.text or ""

        if not self.roles.is_allowed(chat_id, "chat"):
            await update.message.reply_text(
                "❌ You don't have permission to chat with this agent.\n"
                "Contact the owner to upgrade your access."
            )
            return

        # Forward to underlying agent
        response = self._call_agent(chat_id, text)
        await update.message.reply_text(response)

    def _call_agent(self, chat_id: str, message: str) -> str:
        """
        Send a message to the underlying agent and return the response.
        Phase 1: Simple subprocess call to hermes or custom command.
        Phase 2: Will route to per-user Docker container instead.
        """
        agent_type = self.config.agent.type

        try:
            if agent_type == "hermes":
                # TODO: implement proper Hermes integration
                # For now, placeholder
                return f"[Agent received: {message[:100]}]"

            elif self.config.agent.command:
                result = subprocess.run(
                    [self.config.agent.command, message],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return result.stdout.strip() or "Agent returned no response."

            else:
                return "Agent not configured. See config.yaml."

        except subprocess.TimeoutExpired:
            return "⏱️ Agent took too long to respond. Please try again."
        except Exception as e:
            logger.error(f"Agent call failed: {e}")
            return "⚠️ Agent encountered an error. Please try again."
