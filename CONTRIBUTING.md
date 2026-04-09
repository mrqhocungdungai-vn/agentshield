# Contributing to AgentShield

Thank you for wanting to contribute! AgentShield is built by and for the community.

## Ways to Contribute

- **Code** — Pick an issue tagged `good first issue` or `help wanted`
- **Documentation** — Improve READMEs, write tutorials, translate to your language
- **Testing** — Write tests, report bugs, test on different platforms
- **Ideas** — Open a Discussion for feature requests or architecture proposals

## Getting Started

```bash
git clone https://github.com/mrqhocungdungai-vn/agentshield.git
cd agentshield
cp config/example.yaml config/config.yaml
pip install -r requirements.txt
python3 -m pytest tests/
```

## Pull Request Process

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature`
3. Make your changes with tests
4. Run tests: `python3 -m pytest`
5. Open a PR against `main`

## Code Style

- Python: Black formatter, type hints encouraged
- Commits: `feat:`, `fix:`, `docs:`, `test:` prefixes
- Every PR needs at least one test

## Roadmap Ownership

Each phase has an owner label in GitHub Projects:
- Phase 1 (Gateway): anyone can contribute — small, well-scoped tasks
- Phase 2 (Docker): DevOps-focused
- Phase 3 (CRM): Twenty integration specialists
- Phase 4 (Billing): Payment integration experts

## Questions?

Open a GitHub Discussion or join our Discord (link in README).
