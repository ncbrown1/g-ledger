# Contributing to G-Ledger

Thank you for considering contributing to G-Ledger! This document provides guidelines and instructions for developers.

## Development Setup

### Quick Start

```bash
# Clone the repository
git clone <repository-url>
cd g-ledger

# Install development dependencies (auto-creates .venv)
make dev-install

# Run tests
make test

# Check code quality
make check
```

The Makefile automatically creates and uses a `.venv` virtual environment. You don't need to manually create or activate it.

### Manual Setup (Without Make)

If you prefer to manage your own environment:

```bash
# Create your own virtual environment
python3 -m venv my-env
source my-env/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run commands with SKIP_VENV=1
SKIP_VENV=1 make test
```

## Development Workflow

### 1. Make Changes

Edit code in `src/gledger/` following the existing patterns:

- **CLI commands**: Add to `src/gledger/cli.py`
- **Business logic**: Add services to `src/gledger/services/`
- **Data models**: Add Pydantic models to `src/gledger/models/`
- **Data access**: Add repository methods to `src/gledger/repositories/`
- **Configuration**: Extend `src/gledger/config.py`

### 2. Write Tests

Add tests to `tests/` directory:

```bash
# Run tests
make test

# Run with coverage
make test-coverage
```

Test files should be named `test_*.py` and use pytest conventions.

### 3. Format and Lint

Before committing, ensure code quality:

```bash
# Format code (applies changes)
make format

# Lint code (applies fixes)
make lint

# Or check without changes
make format-check
make lint-check
```

### 4. Run Pre-Commit Checks

Before committing, run the full verification:

```bash
make check
```

This runs:
- Code formatting verification (Black)
- Linting (Ruff)
- All tests (pytest)
- Build verification

If this passes, you're ready to commit!

## Code Style

### Python Style

- **Formatting**: Use Black (100 character line length)
- **Linting**: Use Ruff (configured in `pyproject.toml`)
- **Type hints**: Add type hints to function signatures
- **Docstrings**: Add docstrings to modules, classes, and public functions
- **Imports**: Group imports (stdlib, third-party, local)

### Example

```python
"""Module docstring explaining what this module does."""

from datetime import date
from typing import Optional

from pydantic import BaseModel

from ..models.account import Account


def reconcile_account(
    account: Account,
    start_date: Optional[date] = None,
) -> ReconciliationResult:
    """Reconcile account balances for a given period.

    Args:
        account: The account to reconcile
        start_date: Optional start date for reconciliation period

    Returns:
        ReconciliationResult with balance calculations
    """
    # Implementation here
    pass
```

### CLI Commands

When adding CLI commands:

1. Add command to `cli.py`
2. Include comprehensive docstring (shows in `--help`)
3. Add appropriate click options with help text
4. Handle errors gracefully with user-friendly messages
5. Create backup before destructive operations

Example:

```python
@cli.command()
@click.option("--config", type=click.Path(path_type=Path), default=None)
@click.option("--dry-run", is_flag=True, help="Preview changes without executing")
def my_command(config, dry_run):
    """Short description of command.

    Longer description explaining what this command does,
    when to use it, and any important caveats.
    """
    try:
        cfg = Config.load(config)
        # Implementation
        click.echo("✓ Success message")
    except Exception as e:
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)
```

## Testing Guidelines

### Test Structure

```python
class TestFeatureName:
    """Test suite for feature description."""

    def test_specific_behavior(self):
        """Test that specific behavior works correctly."""
        # Arrange
        account = Account(...)

        # Act
        result = reconcile_account(account)

        # Assert
        assert result.is_balanced
```

### Test Coverage

- Aim for high test coverage of business logic
- Test edge cases (zero values, None, empty lists)
- Test error conditions
- Use fixtures for common test data

## Documentation

### When to Update Documentation

Update documentation when:

- Adding new CLI commands → Update README.md usage section
- Adding new features → Update README.md features section
- Changing configuration → Update config.example.yaml and README.md
- Making breaking changes → Update CHANGELOG.md
- Adding dependencies → Justify in commit message

### Documentation Files

- **README.md**: User-facing documentation, features, usage
- **QUICKSTART.md**: 10-minute getting started guide
- **DEPLOYMENT.md**: Production deployment instructions
- **SECURITY.md**: Security best practices
- **CHANGELOG.md**: Version history and changes
- **CONTRIBUTING.md**: This file

## Commit Guidelines

### Commit Messages

Use clear, descriptive commit messages:

```
Add backup functionality to reconcile command

- Creates git snapshot before writing balance snapshots
- Continues on backup failure with warning
- Adds logger initialization to reconcile function
```

### What to Commit

- Source code changes
- Test additions/updates
- Documentation updates
- Configuration examples

### What NOT to Commit

- `config.yaml` (contains secrets)
- `service-account-key.json` (credentials)
- `.venv/` (virtual environment)
- `__pycache__/`, `*.pyc` (Python cache)
- Personal test data

## Debugging

### Enable Debug Logging

```yaml
# In config.yaml
log_level: "DEBUG"
```

### Run Single Test

```bash
pytest tests/test_reconciliation.py::TestSuggestStartingBalance::test_specific_case -v
```

### Check Configuration

```bash
gledger health
```

This verifies:
- Configuration validity
- Credential files
- API connectivity
- Snapshot directory

### Common Issues

**Import Errors**
- Run `make dev-install` to ensure dependencies are installed

**Test Failures**
- Check if you need to update test data after model changes
- Verify fixtures are properly set up

**Linting Failures**
- Run `make format` to auto-fix formatting
- Run `make lint` to auto-fix linting issues

## Making a Pull Request

1. **Create a branch**: `git checkout -b feature/my-feature`
2. **Make changes**: Follow the development workflow above
3. **Run checks**: `make check` must pass
4. **Commit changes**: Use clear commit messages
5. **Update CHANGELOG.md**: Add your changes to `[Unreleased]` section
6. **Push branch**: `git push origin feature/my-feature`
7. **Open PR**: Describe what changed and why

### PR Description Template

```markdown
## Summary
Brief description of changes

## Changes
- Added X feature
- Fixed Y bug
- Updated Z documentation

## Testing
- [ ] Added/updated tests
- [ ] All tests pass (`make check`)
- [ ] Manually tested X scenario

## Documentation
- [ ] Updated README if needed
- [ ] Updated CHANGELOG.md
- [ ] Added docstrings to new code
```

## Questions?

- Check existing code for patterns
- Read the README.md for architecture overview
- Open an issue for clarification
- Ask in discussions

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT).
