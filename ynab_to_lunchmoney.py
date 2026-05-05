#!/usr/bin/env python3
import argparse
import csv
import os
from collections import defaultdict

from lunchmoney_client import LunchMoneyAPIError, LunchMoneyClient, extract_list

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False


load_dotenv()

DEFAULT_BATCH_SIZE = int(os.getenv("LUNCHMONEY_BATCH_SIZE", "500"))
DEFAULT_CURRENCY = os.getenv("LUNCHMONEY_CURRENCY", "sgd").lower()
TRANSFER_CATEGORY_NAME = os.getenv("LUNCHMONEY_TRANSFER_CATEGORY", "Payments & Transfers")


def clean_account_name(name):
    """Keep account name as is, including emojis."""
    return name.strip()


def parse_date(date_str):
    """Convert dd/mm/yyyy to yyyy-mm-dd."""
    day, month, year = date_str.split("/")
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def parse_money(value):
    if not value:
        return 0.0
    cleaned = value.replace("$", "").replace(",", "").strip()
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    return float(cleaned)


def process_transactions(csv_path, limit=None, offset=0):
    """Read and process YNAB transactions."""
    transactions = []
    transfer_pairs = defaultdict(list)

    with open(csv_path, "r", encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader):
            if i < offset:
                continue
            if limit and (i - offset) >= limit:
                break

            if i % 1000 == 0:
                print(f"  Processing row {i}...")

            account = row["Account"]
            flag = row["Flag"]
            date = parse_date(row["Date"])
            payee = row["Payee"]
            category_group = row["Category Group"]
            category = row["Category"]
            memo = row["Memo"]
            outflow = parse_money(row["Outflow"])
            inflow = parse_money(row["Inflow"])
            cleared = row["Cleared"]
            is_transfer = payee.startswith("Transfer :")

            transaction = {
                "account": account,
                "date": date,
                "payee": payee,
                "category": category,
                "category_group": category_group,
                "memo": memo,
                "amount": -outflow if outflow > 0 else inflow,
                "is_transfer": is_transfer,
                "flag": flag,
                "cleared": cleared,
                "original_index": i,
            }

            if is_transfer:
                transfer_key = f"{date}_{memo}"
                transfer_pairs[transfer_key].append(transaction)

            transactions.append(transaction)

    return transactions, transfer_pairs


def create_lunch_money_transaction(txn, manual_account_id, category_id=None, tag_ids=None, currency=DEFAULT_CURRENCY):
    tag_ids = tag_ids or []

    # Lunch Money inserts use positive numbers for debits and negative numbers for credits.
    amount = abs(txn["amount"]) if txn["amount"] < 0 else -abs(txn["amount"])
    payee = txn["payee"].replace("Transfer : ", "") if txn["is_transfer"] else txn["payee"]

    lm_txn = {
        "date": txn["date"],
        "amount": amount,
        "payee": payee,
        "currency": currency,
        "manual_account_id": manual_account_id,
        "notes": txn["memo"] if txn["memo"] else None,
        "status": "reviewed" if txn["cleared"] == "Cleared" else "unreviewed",
        "external_id": f"ynab-csv-{txn['original_index']}",
    }

    if category_id:
        lm_txn["category_id"] = category_id

    if tag_ids:
        lm_txn["tag_ids"] = tag_ids

    return lm_txn


def flatten_categories(categories):
    flattened = []
    for category in categories:
        flattened.append(category)
        flattened.extend(flatten_categories(category.get("children", [])))
    return flattened


def get_existing_manual_accounts(client):
    payload = client.get("/manual_accounts")
    accounts = extract_list(payload, "manual_accounts")
    account_map = {}
    for account in accounts:
        for name in (account.get("name"), account.get("display_name")):
            if name:
                account_map[name.strip().lower()] = account
    return account_map


def get_existing_categories(client):
    payload = client.get("/categories", params={"format": "flattened"})
    categories = extract_list(payload, "categories")
    categories = flatten_categories(categories)
    return {
        (category.get("name") or "").strip().lower(): category
        for category in categories
        if not category.get("is_group")
    }


def get_existing_tags(client):
    payload = client.get("/tags")
    tags = extract_list(payload, "tags")
    return {
        (tag.get("name") or "").strip().lower(): tag
        for tag in tags
        if not tag.get("archived_at") and not tag.get("archived")
    }


def get_or_create_manual_accounts(client, account_names, currency):
    existing_accounts = get_existing_manual_accounts(client)
    account_map = {}

    for account_name in sorted(account_names):
        cleaned_name = clean_account_name(account_name)
        existing = existing_accounts.get(cleaned_name.lower())
        if existing:
            account_map[account_name] = existing["id"]
            print(f"Found manual account: {cleaned_name} (ID: {existing['id']})")
            continue

        payload = {
            "type": "cash",
            "name": cleaned_name,
            "balance": 0,
            "currency": currency,
            "external_id": f"ynab-csv-account-{cleaned_name.lower()}",
        }
        created = client.post("/manual_accounts", json=payload)
        account_map[account_name] = created["id"]
        existing_accounts[cleaned_name.lower()] = created
        print(f"Created manual account: {cleaned_name} (ID: {created['id']})")

    return account_map


def get_or_create_categories(client, categories):
    existing_categories = get_existing_categories(client)
    category_map = {}

    required_categories = {TRANSFER_CATEGORY_NAME: None}
    required_categories.update(categories)

    for category_name, category_group in sorted(required_categories.items()):
        existing = existing_categories.get(category_name.lower()) or existing_categories.get(category_name[:40].lower())
        if existing:
            category_map[category_name] = existing["id"]
            print(f"Found category: {category_name} (ID: {existing['id']})")
            continue

        payload = {
            "name": category_name[:40],
            "description": f"From YNAB: {category_group}" if category_group else "From YNAB",
        }
        created = client.post("/categories", json=payload)
        category_map[category_name] = created["id"]
        existing_categories[category_name.lower()] = created
        print(f"Created category: {category_name} (ID: {created['id']})")

    category_map["_transfer"] = category_map[TRANSFER_CATEGORY_NAME]
    return category_map


def get_or_create_tags(client, tag_names):
    existing_tags = get_existing_tags(client)
    tag_map = {}

    for tag_name in sorted(tag_names):
        existing = existing_tags.get(tag_name.lower())
        if existing:
            tag_map[tag_name] = existing["id"]
            print(f"Found tag: {tag_name} (ID: {existing['id']})")
            continue

        created = client.post("/tags", json={"name": tag_name})
        tag_map[tag_name] = created["id"]
        existing_tags[tag_name.lower()] = created
        print(f"Created tag: {tag_name} (ID: {created['id']})")

    return tag_map


def build_lunch_money_transactions(transactions, account_map, category_map, tag_map, currency):
    lm_transactions = []

    for txn in transactions:
        if txn["account"] not in account_map:
            print(f"Skipping transaction - no manual account mapping for {txn['account']}")
            continue

        if txn["is_transfer"]:
            category_id = category_map.get("_transfer")
        elif txn["category"]:
            category_id = category_map.get(txn["category"])
        else:
            category_id = None

        tag_ids = []
        if txn["flag"] and txn["flag"] not in ["", "Not Counted"]:
            tag_id = tag_map.get(txn["flag"])
            if tag_id:
                tag_ids.append(tag_id)

        lm_txn = create_lunch_money_transaction(
            txn,
            account_map[txn["account"]],
            category_id=category_id,
            tag_ids=tag_ids,
            currency=currency,
        )
        lm_transactions.append(lm_txn)

        if len(lm_transactions) <= 10:
            print(
                f"  {txn['date']} | {txn['payee'][:30]:30} | "
                f"${abs(txn['amount']):8.2f} | {txn['account'][:20]}"
            )

    return lm_transactions


def insert_transactions(client, lm_transactions, batch_size):
    total_inserted = 0
    total_skipped = 0
    total_batches = (len(lm_transactions) + batch_size - 1) // batch_size

    for i in range(0, len(lm_transactions), batch_size):
        batch = lm_transactions[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        print(f"  Batch {batch_num}/{total_batches}: inserting {len(batch)} transactions...")

        payload = {
            "transactions": batch,
            "apply_rules": False,
            "check_for_recurring": False,
            "skip_duplicates": True,
        }

        result = client.post("/transactions", json=payload)
        inserted = result.get("transactions", [])
        skipped = result.get("skipped_duplicates", [])
        total_inserted += len(inserted)
        total_skipped += len(skipped)
        print(f"    Inserted {len(inserted)} transactions; skipped {len(skipped)} duplicates")

    return total_inserted, total_skipped


def main():
    parser = argparse.ArgumentParser(description="Migrate YNAB CSV transactions to Lunch Money v2.")
    parser.add_argument("--file", default="register.csv", help="Path to the YNAB register CSV export.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Transaction insert batch size.")
    parser.add_argument("--currency", default=DEFAULT_CURRENCY, help="Lunch Money currency code.")
    parser.add_argument("--limit", type=int, default=None, help="Only process this many CSV rows.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many CSV rows before processing.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and prepare transactions without API calls.")
    args = parser.parse_args()

    print("Starting YNAB to Lunch Money v2 migration...")
    print(f"Reading transactions from {args.file}...")
    transactions, transfer_pairs = process_transactions(args.file, limit=args.limit, offset=args.offset)
    print(f"Done reading {len(transactions)} transactions")
    print(f"Found {len(transfer_pairs)} potential transfer pairs")

    accounts = set()
    categories = {}
    tag_names = set()

    for txn in transactions:
        accounts.add(txn["account"])
        if txn["category"] and not txn["is_transfer"]:
            categories[txn["category"]] = txn["category_group"]
        if txn["flag"] and txn["flag"] not in ["", "Not Counted"]:
            tag_names.add(txn["flag"])

    print(f"\nUnique accounts: {len(accounts)}")
    print(f"Unique categories: {len(categories) + 1}")
    print(f"Unique tags: {len(tag_names)}")

    if args.dry_run:
        fake_account_map = {account: index for index, account in enumerate(sorted(accounts), start=1)}
        fake_category_map = {
            category: index for index, category in enumerate(sorted(categories.keys()), start=1)
        }
        fake_category_map["_transfer"] = len(fake_category_map) + 1
        fake_tag_map = {tag: index for index, tag in enumerate(sorted(tag_names), start=1)}
        lm_transactions = build_lunch_money_transactions(
            transactions, fake_account_map, fake_category_map, fake_tag_map, args.currency.lower()
        )
        print(f"\nDry run complete. Prepared {len(lm_transactions)} transactions; no API calls made.")
        return

    client = LunchMoneyClient()

    print("\n=== Creating/Matching Manual Accounts ===")
    account_map = get_or_create_manual_accounts(client, accounts, args.currency.lower())

    print("\n=== Creating/Matching Categories ===")
    category_map = get_or_create_categories(client, categories)

    print("\n=== Creating/Matching Tags ===")
    tag_map = get_or_create_tags(client, tag_names)

    print("\n=== Preparing Transactions ===")
    lm_transactions = build_lunch_money_transactions(
        transactions, account_map, category_map, tag_map, args.currency.lower()
    )

    print(f"\n=== Inserting {len(lm_transactions)} Transactions ===")
    total_inserted, total_skipped = insert_transactions(client, lm_transactions, args.batch_size)

    print("\n=== Migration Complete ===")
    print(f"Inserted {total_inserted} transactions; skipped {total_skipped} duplicates.")
    print("Please check your Lunch Money account to verify the transactions.")
    print("\nNote: Transfers are created as separate transactions with the transfer category.")
    print("You may need to manually link them in Lunch Money if needed.")


if __name__ == "__main__":
    try:
        main()
    except LunchMoneyAPIError as exc:
        print(f"Migration failed: {exc}")
        raise SystemExit(1)
