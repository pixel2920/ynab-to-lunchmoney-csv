#!/usr/bin/env python3
import csv
import json
import requests
import os
import re
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

LUNCH_MONEY_TOKEN = os.getenv('LUNCHMONEY_TOKEN')
BASE_URL = 'https://dev.lunchmoney.app/v1'

headers = {
    'Authorization': f'Bearer {LUNCH_MONEY_TOKEN}',
    'Content-Type': 'application/json'
}

def clean_account_name(name):
    """Keep account name as is, including emojis"""
    return name.strip()

def parse_date(date_str):
    """Convert dd/mm/yyyy to yyyy-mm-dd"""
    day, month, year = date_str.split('/')
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

def get_or_create_category(category_name, category_group=None):
    """Get existing category or create new one"""
    # First, get all categories
    response = requests.get(f"{BASE_URL}/categories", headers=headers)
    if response.status_code == 200:
        categories = response.json().get('categories', [])
        for cat in categories:
            if cat['name'].lower() == category_name.lower():
                return cat['id']

    # Create new category if not found
    payload = {
        'name': category_name[:40],  # Max 40 chars
        'description': f"From YNAB: {category_group}" if category_group else "From YNAB"
    }

    response = requests.post(f"{BASE_URL}/categories", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()['category_id']
    else:
        print(f"Failed to create category {category_name}: {response.text}")
        return None

def get_or_create_asset(account_name):
    """Get existing asset or create new one"""
    cleaned_name = clean_account_name(account_name)

    # Get existing assets
    response = requests.get(f"{BASE_URL}/assets", headers=headers)
    if response.status_code == 200:
        assets = response.json().get('assets', [])
        for asset in assets:
            if asset['name'].lower() == cleaned_name.lower():
                return asset['id']

    # Create new asset
    payload = {
        'type_name': 'cash',
        'name': cleaned_name,
        'balance': 0,
        'currency': 'sgd'
    }

    response = requests.post(f"{BASE_URL}/assets", headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()['id']
    else:
        print(f"Failed to create asset {cleaned_name}: {response.text}")
        return None

def process_transactions(limit=None, offset=0):
    """Read and process YNAB transactions"""
    transactions = []
    transfer_pairs = defaultdict(list)

    with open('register.csv', 'r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader):
            if i < offset:
                continue
            if limit and (i - offset) >= limit:
                break

            if i % 1000 == 0:
                print(f"  Processing row {i}...")

            # Parse the row
            account = row['Account']
            flag = row['Flag']
            date = parse_date(row['Date'])
            payee = row['Payee']
            category_group = row['Category Group']
            category = row['Category']
            memo = row['Memo']
            outflow = float(row['Outflow'].replace('$', '').replace(',', '')) if row['Outflow'] else 0
            inflow = float(row['Inflow'].replace('$', '').replace(',', '')) if row['Inflow'] else 0
            cleared = row['Cleared']

            # Determine if it's a transfer
            is_transfer = payee.startswith('Transfer :')

            transaction = {
                'account': account,
                'date': date,
                'payee': payee,
                'category': category,
                'category_group': category_group,
                'memo': memo,
                'amount': -outflow if outflow > 0 else inflow,
                'is_transfer': is_transfer,
                'flag': flag,
                'cleared': cleared,
                'original_index': i
            }

            # Group transfers by date and memo for matching
            if is_transfer:
                transfer_key = f"{date}_{memo}"
                transfer_pairs[transfer_key].append(transaction)

            transactions.append(transaction)

    return transactions, transfer_pairs

def create_lunch_money_transaction(txn, asset_id, category_id=None):
    """Create a single transaction in Lunch Money format"""
    tags = []
    if txn['flag'] and txn['flag'] not in ['', 'Not Counted']:
        tags.append(txn['flag'])

    # For Lunch Money, expenses are positive, income is negative
    # YNAB: outflow is positive (expense), inflow is positive (income)
    # So we need: outflow -> positive amount, inflow -> negative amount
    if txn['amount'] < 0:
        # This was an outflow in YNAB (expense)
        amount = abs(txn['amount'])
    else:
        # This was an inflow in YNAB (income)
        amount = -abs(txn['amount'])

    lm_txn = {
        'date': txn['date'],
        'amount': amount,
        'payee': txn['payee'].replace('Transfer : ', '') if txn['is_transfer'] else txn['payee'],
        'currency': 'sgd',
        'asset_id': asset_id,
        'notes': txn['memo'] if txn['memo'] else None,
        'status': 'cleared' if txn['cleared'] == 'Cleared' else 'uncleared'
    }

    if category_id:
        lm_txn['category_id'] = category_id

    if tags:
        lm_txn['tags'] = tags

    return lm_txn

def main():
    print("Starting FULL YNAB to Lunch Money migration...")
    print("Processing ALL transactions...")
    import sys
    sys.stdout.flush()

    # Process ALL transactions
    print("Reading transactions from CSV...")
    sys.stdout.flush()
    transactions, transfer_pairs = process_transactions()
    print(f"Done reading {len(transactions)} transactions")
    sys.stdout.flush()

    print(f"\nFound {len(transactions)} transactions to migrate")
    print(f"Found {len(transfer_pairs)} potential transfer pairs")

    # Collect unique accounts and categories
    accounts = set()
    categories = {}

    for txn in transactions:
        accounts.add(txn['account'])
        if txn['category'] and not txn['is_transfer']:
            categories[txn['category']] = txn['category_group']

    print(f"\nUnique accounts: {len(accounts)}")
    for acc in accounts:
        print(f"  - {acc} -> {clean_account_name(acc)}")

    print(f"\nUnique categories: {len(categories)}")
    for cat, group in categories.items():
        print(f"  - {cat} (Group: {group})")

    # Create assets in Lunch Money
    print("\n=== Creating Assets ===")
    asset_map = {}
    for account in accounts:
        asset_id = get_or_create_asset(account)
        if asset_id:
            asset_map[account] = asset_id
            print(f"✓ Created/Found asset: {clean_account_name(account)} (ID: {asset_id})")
        else:
            print(f"✗ Failed to create asset: {account}")

    # Create categories
    print("\n=== Creating Categories ===")
    category_map = {}

    # Always create transfer category
    transfer_cat_id = get_or_create_category("Payments & Transfers")
    category_map['_transfer'] = transfer_cat_id
    print(f"✓ Created/Found transfer category (ID: {transfer_cat_id})")

    for category, group in categories.items():
        cat_id = get_or_create_category(category, group)
        if cat_id:
            category_map[category] = cat_id
            print(f"✓ Created/Found category: {category} (ID: {cat_id})")
        else:
            print(f"✗ Failed to create category: {category}")

    # Prepare transactions for insertion
    print("\n=== Preparing Transactions ===")
    lm_transactions = []

    for txn in transactions:
        if txn['account'] not in asset_map:
            print(f"Skipping transaction - no asset mapping for {txn['account']}")
            continue

        asset_id = asset_map[txn['account']]

        # Determine category
        if txn['is_transfer']:
            category_id = category_map.get('_transfer')
        elif txn['category']:
            category_id = category_map.get(txn['category'])
        else:
            category_id = None

        lm_txn = create_lunch_money_transaction(txn, asset_id, category_id)
        lm_transactions.append(lm_txn)

        # Only print first few for debugging
        if len(lm_transactions) <= 10:
            print(f"  {txn['date']} | {txn['payee'][:30]:30} | ${abs(txn['amount']):8.2f} | {txn['account'][:20]}")

    # Insert transactions in batches of 500 (Lunch Money limit)
    print(f"\n=== Inserting {len(lm_transactions)} Transactions ===")

    batch_size = 500
    total_inserted = 0

    for i in range(0, len(lm_transactions), batch_size):
        batch = lm_transactions[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(lm_transactions) + batch_size - 1) // batch_size

        print(f"  Batch {batch_num}/{total_batches}: Inserting {len(batch)} transactions...")

        payload = {
            'transactions': batch,
            'apply_rules': False,
            'check_for_recurring': False,
            'debit_as_negative': False
        }

        response = requests.post(f"{BASE_URL}/transactions", headers=headers, json=payload)

        if response.status_code == 200:
            result = response.json()
            inserted_ids = result.get('ids', [])
            total_inserted += len(inserted_ids)
            print(f"    ✓ Successfully inserted {len(inserted_ids)} transactions")
        else:
            print(f"    ✗ Failed batch: {response.status_code}")
            print(f"      Error: {response.text[:200]}")

    print("\n=== Migration Complete ===")
    print("Please check your Lunch Money account to verify the transactions!")
    print("\nNote: Transfers are created as separate transactions with 'Payments & Transfers' category.")
    print("You may need to manually link them in Lunch Money if needed.")

if __name__ == "__main__":
    main()