# YNAB to Lunch Money Migration Tool

A Python script to migrate your YNAB (You Need A Budget) transaction data to Lunch Money via API.

## Features

- Migrates all transactions from YNAB CSV export to Lunch Money
- Preserves account names (including emojis)
- Handles transfers correctly (one positive, one negative)
- Maps YNAB categories to Lunch Money categories automatically
- Converts date format from DD/MM/YYYY to YYYY-MM-DD
- Maps YNAB flags to Lunch Money tags
- Uses the Lunch Money v2 API
- Batch processing for large datasets (defaults to 500 transactions at a time)
- Handles Lunch Money rate limits by respecting `Retry-After` and rate limit reset headers
- Caches accounts, categories, and tags to reduce API calls
- Uses stable external IDs and `skip_duplicates` to make repeat imports safer
- Bulk update account types after migration

## Prerequisites

- Python 3.6+
- A Lunch Money account with API access
- Your YNAB transaction data exported as CSV

## Setup

1. Clone this repository:
```bash
git clone https://github.com/yjsoon/ynab-to-lunchmoney-csv.git
cd ynab-to-lunchmoney-csv
```

2. Install dependencies:
```bash
pip install requests python-dotenv
```

3. Create a `.env` file from the example:
```bash
cp .env.example .env
```

4. Edit `.env` and add your API tokens:
   - **Lunch Money API Token**: Get yours at https://my.lunchmoney.app/developers
   - **YNAB API Token** (optional): Get yours at https://app.youneedabudget.com/settings/developer

Optional `.env` settings:

```bash
LUNCHMONEY_CURRENCY=sgd
LUNCHMONEY_BATCH_SIZE=500
LUNCHMONEY_RATE_LIMIT_BUFFER=5
LUNCHMONEY_MAX_RETRIES=5
```

## Getting Your YNAB Data

1. Log in to YNAB
2. Go to **All Accounts** view
3. Select all transactions (Ctrl+A or Cmd+A)
4. Click **Export** → **Export CSV**
5. Save the file as `register.csv` in this directory

## Usage

### Migrating Transactions

Run the main migration script:

```bash
python3 ynab_to_lunchmoney.py
```

You can also run a dry run without any Lunch Money API calls:

```bash
python3 ynab_to_lunchmoney.py --dry-run
```

Useful options:

```bash
python3 ynab_to_lunchmoney.py --file register.csv --currency usd --batch-size 500
```

The script will:
1. Read your `register.csv` file
2. Create/match all YNAB accounts as Lunch Money manual accounts
3. Create categories and tags as needed
4. Import all transactions in batches via the Lunch Money v2 API
5. Show progress as it processes

### Updating Account Types

After migration, you can bulk update account types (cash, credit, investment, etc.):

```bash
python3 update_account_types.py
```

The default rule sets:
- Accounts with numbers in the name → credit
- All other accounts → cash

You can edit `update_account_types.py` to customize the mapping rules.

## Important Notes

### Date Format
The script assumes your YNAB export uses DD/MM/YYYY format. If your YNAB uses MM/DD/YYYY, edit the `parse_date` function in `ynab_to_lunchmoney.py`.

### Transfers
YNAB transfers are automatically detected (they start with "Transfer :") and handled correctly - one account shows positive, the other negative.

### Large Datasets
The script processes transactions in batches of 500 by default. You may change this with `--batch-size` or `LUNCHMONEY_BATCH_SIZE`, but 500 remains the safest default unless Lunch Money documents a higher transaction insert limit for your account.

### Duplicate Prevention
The script uses a get-or-create pattern for manual accounts, categories, and tags to avoid duplicates. It also sends a stable `external_id` for each CSV row and uses `skip_duplicates` when inserting transactions so rerunning the same CSV is safer.

### Account Name Mapping
The script preserves emoji and special characters in account names. These are matched exactly when creating assets in Lunch Money.

## Troubleshooting

### UnicodeDecodeError
If you get encoding errors with your CSV file, the script already handles UTF-8 BOM markers. If issues persist, try saving your CSV with UTF-8 encoding in a text editor.

### API Rate Limits
The script implements rate limit handling for Lunch Money's v2 API. It respects `Retry-After` after a `429 Too Many Requests` response and will pause proactively when the remaining request count falls below `LUNCHMONEY_RATE_LIMIT_BUFFER`.

### Missing Transactions
Check that your CSV export includes all accounts and cleared/uncleared transactions. The script will skip transactions with empty amounts.

## Contributing

Feel free to open issues or submit pull requests if you find bugs or have improvements!

## License

MIT

## Disclaimer

This is an unofficial tool not affiliated with YNAB or Lunch Money. Use at your own risk. Always backup your data before running migrations.
