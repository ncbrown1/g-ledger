# G-Ledger Quick Start Guide

This guide gets you up and running with G-Ledger in 10 minutes.

## Prerequisites

- Python 3.10+
- Google account
- SimpleFIN account with bank connections
- Git

## Step 1: Install (2 minutes)

```bash
cd g-ledger
pip install -e .
```

## Step 2: Google Cloud Setup (3 minutes)

1. Go to https://console.cloud.google.com/
2. Create/select project
3. Enable "Google Sheets API"
4. Create Service Account:
   - APIs & Services > Credentials > Create Credentials > Service Account
   - Name: "gledger-sync"
   - Create and download JSON key → save as `service-account-key.json`
5. Note the service account email (e.g., `gledger-sync@project.iam.gserviceaccount.com`)

## Step 3: Create Google Sheet (1 minute)

1. Create new Google Sheet: https://sheets.google.com
2. Name it "G-Ledger"
3. Copy Sheet ID from URL:
   ```
   https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit
   ```
4. Share with service account email (Editor access)

## Step 4: Configure (1 minute)

```bash
cp config.example.yaml config.yaml
nano config.yaml  # or your editor
```

Fill in:
- `sheet_id`: From step 3
- `service_account_key_path`: `./service-account-key.json`
- `simplefin_token`: Your SimpleFIN access token

## Step 5: Bootstrap (1 minute)

```bash
gledger bootstrap-sheet
```

This creates the Accounts, Transactions, Categories, and Balance History tabs with proper structure.

## Step 6: Sync Accounts (1 minute)

Fetch your SimpleFIN accounts and add them to the sheet:

```bash
# Preview accounts first
gledger accounts-sync --list-only

# Sync them to the sheet
gledger accounts-sync
```

This automatically creates rows in the **Accounts** tab for each SimpleFIN account (disabled by default).

Now open your Google Sheet, go to the **Accounts** tab, and for each account:
1. Set `enabled` to TRUE
2. Optionally customize `display_name`
3. Save the sheet

## Step 7: First Sync! (30 seconds)

```bash
gledger sync
```

This fetches the last 30 days of transactions and populates the Transactions tab.

## Step 8: Review Transactions (ongoing)

1. Open sheet on mobile/desktop
2. Filter Transactions by `needs_attention = TRUE`
3. For each transaction:
   - Set `category` (use dropdown)
   - Verify amount and payee are correct

## Step 9: Set Up Reconciliation (optional)

```bash
# Suggest starting balances for your accounts
gledger reconcile --suggest-starting-balance

# Review suggestions and approve them
# Then sync again to compute reconciliation status
gledger accounts-sync
```

## Daily Workflow

### Automated (Recommended)

Set up cron:
```bash
crontab -e
# Add: 0 6 * * * cd /path/to/g-ledger && gledger sync
```

### Manual

```bash
# Sync transactions
gledger sync

# Review in Google Sheet (mobile-friendly)
# ...
```

## Pro Tips

### Splitting Transactions

If a $100 grocery transaction includes $30 of household items:

1. Find BANK row with `txn_key = "ACC123:TXN456"`
2. Add two SPLIT rows:
   - Row 1: `txn_key = "ACC123:TXN456"`, `row_role = SPLIT`, `category = "Expenses:Groceries"`, `amount = -70`
   - Row 2: `txn_key = "ACC123:TXN456"`, `row_role = SPLIT`, `category = "Expenses:Home"`, `amount = -30`
3. Set BANK row `amount = 0`

### Manual Transactions

For cash purchases:

Add row to Transactions:
- `txn_key`: `MANUAL:2024-01-15-coffee` (unique ID)
- `row_role`: `MANUAL`
- `date`: `2024-01-15`
- `amount`: `-5.00`
- `category`: `Expenses:Dining`
- `account_name`: `Cash` or `Manual Entry`

### Viewing Snapshots

```bash
gledger list-snapshots
```

### Restoring

```bash
gledger restore <commit_hash>
```

## Troubleshooting

**"No enabled accounts"**
→ Check Accounts tab, set `enabled = TRUE`

**"Headers don't match"**
→ Don't edit header rows. Delete tab and run `bootstrap-sheet` again.

**"Split mismatch"**
→ Ensure SPLIT amounts sum exactly to BANK `sf_amount`

## Next Steps

- Read full [README.md](README.md) for detailed documentation
- Explore review status filters
- Set up monthly reconciliation workflow
- Customize categories in Categories tab

## Need Help?

- Check [README.md](README.md) troubleshooting section
- SimpleFIN docs: https://beta-bridge.simplefin.org/

Happy accounting! 📊
