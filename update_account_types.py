#!/usr/bin/env python3
import requests
import os
import re
from dotenv import load_dotenv

load_dotenv()

LUNCH_MONEY_TOKEN = os.getenv('LUNCHMONEY_TOKEN')
BASE_URL = 'https://dev.lunchmoney.app/v1'

headers = {
    'Authorization': f'Bearer {LUNCH_MONEY_TOKEN}',
    'Content-Type': 'application/json'
}

def update_account_types():
    # Get all assets
    response = requests.get(f"{BASE_URL}/assets", headers=headers)
    if response.status_code != 200:
        print(f"Failed to get assets: {response.text}")
        return

    assets = response.json().get('assets', [])
    print(f"Found {len(assets)} assets in Lunch Money\n")

    for asset in assets:
        asset_id = asset['id']
        asset_name = asset['display_name'] or asset['name']
        current_type = asset.get('type_name', 'unknown')

        # Check if account name has numbers
        has_numbers = bool(re.search(r'\d', asset_name))

        if has_numbers:
            new_type = 'credit'
        else:
            new_type = 'cash'  # Default for accounts without numbers

        if current_type != new_type:
            print(f"Updating '{asset_name}': {current_type} → {new_type}")

            # Update the asset
            payload = {
                'type_name': new_type
            }

            update_response = requests.put(
                f"{BASE_URL}/assets/{asset_id}",
                headers=headers,
                json=payload
            )

            if update_response.status_code == 200:
                print(f"  ✓ Updated successfully")
            else:
                print(f"  ✗ Failed: {update_response.text}")
        else:
            print(f"'{asset_name}': already {current_type} (no change)")

if __name__ == "__main__":
    print("Updating Lunch Money account types...")
    print("Rule: Accounts with numbers → credit, others → cash\n")
    update_account_types()
    print("\nDone!")