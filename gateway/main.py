"""
AgentShield Gateway — Phase 1
Telegram gateway with role-based access control for AI agents.

Usage:
    python3 -m gateway.main --config config/config.yaml
"""

import asyncio
import logging
import sys
from pathlib import Path

from gateway.config import load_config
from gateway.bot import AgentShieldBot


def main():
    config_path = Path("config/config.yaml")
    if len(sys.argv) > 2 and sys.argv[1] == "--config":
        config_path = Path(sys.argv[2])

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        print("Copy config/example.yaml to config/config.yaml and fill in your values.")
        sys.exit(1)

    config = load_config(config_path)

    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = AgentShieldBot(config)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
