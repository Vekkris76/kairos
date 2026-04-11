# Contributing to Autopilot Engine

Thank you for your interest in contributing! Here's how to get started.

## Quick Start

```bash
git clone https://github.com/Vekkris76/autopilot-engine.git
cd autopilot-engine
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Development Workflow

1. **Fork** the repository
2. **Create a branch**: `git checkout -b feature/my-feature`
3. **Make changes** and add tests
4. **Run checks**: `ruff check autopilot/ && pytest`
5. **Commit**: `git commit -m "feat: add my feature"`
6. **Push**: `git push origin feature/my-feature`
7. **Open a Pull Request**

## Code Style

- Python 3.11+
- Ruff for linting (100 char line length)
- Type hints on all public methods
- Docstrings on all public classes and methods
- No external dependencies without discussion

## Architecture Rules

1. **Pure Python** — No Cython, no Rust, no compiled extensions
2. **No exchange-specific code in core** — All exchange logic in `exchanges/`
3. **Strategies never import exchange modules** — They use the Strategy base class only
4. **Every indicator is a standalone file** — Easy to understand and modify
5. **Every feature has a test** — No untested code in main

## Areas Where We Need Help

- **New indicators** — Add to `autopilot/indicators/`
- **Exchange adapters** — Bybit, Kraken, OKX...
- **Documentation** — Tutorials, examples, translations
- **Backtesting** — Fill models, performance metrics
- **Bug reports** — Test edge cases, report issues

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add Bollinger Bands indicator
fix: handle WebSocket reconnection on timeout
docs: add backtesting guide
test: add RSI edge case tests
refactor: simplify order manager state machine
```

## Questions?

Open an issue or join our community discussions on GitHub.
