"""G-Ledger: Transaction sync system between SimpleFIN and Google Sheets.

G-Ledger automatically syncs bank transactions from SimpleFIN into a Google Sheet,
computes review status, supports transaction splits and manual entries, and provides
git-based snapshots for version control.

Main components:
- CLI: Command-line interface (cli.py)
- Config: Configuration management with validation (config.py)
- Services: Business logic for sync, reconciliation, and SimpleFIN integration
- Repositories: Data access for Google Sheets and snapshots
- Models: Pydantic data models for accounts, transactions, and balance history
- Bootstrap: Sheet initialization and schema setup

For usage information, run:
    gledger --help

For detailed documentation, see README.md
"""

__version__ = "0.1.0"
__author__ = "G-Ledger Contributors"
