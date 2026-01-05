# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

No unreleased changes yet.

## [0.1.0] - 2025-01-05

### Added - Core Features
- **SimpleFIN Integration**: Automatically fetch posted transactions from bank accounts
- **Google Sheets as Source of Truth**: All transaction data stored and managed in Google Sheet
- **Transaction Splits**: Split a single bank transaction across multiple expense categories
- **Manual Transactions**: Add manual transactions not from SimpleFIN
- **Account Reconciliation**: Track reconciliation status per account with cutoff dates and starting balances
- **Balance History Tracking**: Historical account balance snapshots with `is_starting_balance` flag
- **Git-based Snapshots**: Automatic versioning with git commits before/after each sync
- **Review Status System**: Automatic flagging of new, changed, or problematic transactions
- **Idempotent Sync**: Running sync multiple times produces no duplicates
- **Batched Sync**: Large date ranges (>60 days) automatically batched to reduce memory pressure

### Added - Production Readiness
- **Health check command**: `gledger health` verifies configuration, credentials, and API connectivity
- **Comprehensive config validation**: Validates sheet IDs, URLs, file permissions, and service account keys with actionable error messages
- **Automatic backups**: All write operations (sync-accounts, reconcile --suggest-starting-balance) create git snapshots before modifying data
- **Confirmation prompts**: Bootstrap command shows what will be created and asks for confirmation
- **Virtual environment auto-detection**: Makefile automatically creates and uses `.venv` for consistent development environment
- **Pre-commit verification**: `make check` runs formatting, linting, tests, and build verification
- **Production documentation**: SECURITY.md, README.md with motivation, DEPLOYMENT.md, QUICKSTART.md, and CONTRIBUTING.md

### Added - Developer Experience
- **Comprehensive test suite**: 71 unit tests with full coverage of reconciliation workflow
- **End-to-end reconciliation tests**: Zero balance handling and workflow validation
- **Make-based workflow**: `make dev-install`, `make test`, `make check`, `make clean-venv`
- **Code quality tools**: Black formatter, Ruff linter, pytest with coverage
- **CLI interface**: User-friendly commands with comprehensive help text

### Added - CLI Commands
- `gledger bootstrap-sheet`: Initialize Google Sheet with proper schema and protections
- `gledger sync-accounts`: Sync SimpleFIN accounts to Google Sheet
- `gledger sync`: Sync SimpleFIN transactions to Google Sheet
- `gledger reconcile`: Reconcile account balances with starting balance suggestions
- `gledger health`: Check system health and configuration
- `gledger list-snapshots`: List recent git snapshots
- `gledger restore`: Restore Google Sheet from a snapshot

### Fixed
- Zero balance handling in reconciliation
- Date parsing from Excel serial numbers
- Import errors in CLI commands
- Linting errors (unused variables, bare excepts)
- Makefile Python compatibility (uses `python3` consistently)

### Changed
- Enhanced Makefile with lint-check, format-check, and venv management
- Bootstrap command includes detailed description and confirmation
- README updated with "Why This Project?" section and Makefile-based development workflow

[Unreleased]: https://github.com/yourusername/g-ledger/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/g-ledger/releases/tag/v0.1.0
