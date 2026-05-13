# Contributing to Local Lucy

Thank you for your interest in contributing to Local Lucy! This document provides guidelines for participating in the project.

## Getting Started

### Development Environment

```bash
# Clone your fork
git clone git@github.com:YOUR_USERNAME/Local-Lucy.git
cd Local-Lucy

# Create virtual environment
python3 -m venv ui-v8/.venv
source ui-v8/.venv/bin/activate

# Install dependencies
pip install -r ui-v8/requirements.txt

# Verify setup
python3 -m pytest tools/router_py/ -q
```

### Project Conventions

- **Python 3.10+** with type hints encouraged
- **pytest** for all tests
- **Prefer `StrReplaceFile` over `WriteFile`** for edits
- **Prefer Python over shell** for logic
- **No optimistic behavior** — validate assumptions
- **No silent side effects** — log every significant action
- **Test every change** — all tests must pass before submission

## Making Changes

1. **Create a feature branch**
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes** with clear, focused commits

3. **Run tests**
   ```bash
   # Router tests (430+)
   python3 -m pytest tools/router_py/ -q

   # Model tests
   python3 -m pytest models/router/ -q

   # E2E tests
   python3 -m pytest tools/tests/test_end_to_end_comprehensive.py -q
   ```

4. **Ensure clean git status**
   ```bash
   git status  # should show only intended changes
   ```

## Commit Message Format

Use conventional commits:

```
feat(router): add embedding collapse detection for short queries
fix(voice): resolve sample rate mismatch in Kokoro output
docs(readme): update installation instructions
test(learner): add threshold boundary tests
chore(cleanup): remove legacy shell scripts
```

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **test**: Adding or updating tests
- **chore**: Maintenance tasks
- **refactor**: Code restructuring without behavior change

## Pull Request Process

1. Ensure all tests pass locally
2. Update relevant documentation (README, ARCHITECTURE, AGENTS)
3. Fill out the pull request template
4. Request review from maintainers
5. Address feedback promptly

## Code Review Criteria

Pull requests are evaluated on:

- **Correctness** — Does it work? Are edge cases handled?
- **Tests** — Are there tests? Do they pass?
- **Documentation** — Is the change explained?
- **Minimalism** — Is the change as small as possible?
- **Safety** — Could this break production data or state?

## Areas for Contribution

Priority areas where help is welcome:

- **Embedding model benchmarking** — Compare ModernBERT vs all-MiniLM-L6-v2
- **Memory service migrations** — Add versioned schema control to `tools/memory/`
- **Cross-platform support** — Windows and macOS compatibility
- **Additional providers** — New data source integrations
- **Performance optimization** — Latency reduction, memory usage

## Questions?

Open an issue with the `question` label or reach out via the project's discussion board.

## Code of Conduct

Be respectful, constructive, and inclusive. Disagreements are fine — personal attacks are not.
