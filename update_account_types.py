#!/usr/bin/env python3
import re

from lunchmoney_client import LunchMoneyAPIError, LunchMoneyClient, extract_list

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False


load_dotenv()


def update_account_types():
    client = LunchMoneyClient()
    payload = client.get("/manual_accounts")
    accounts = extract_list(payload, "manual_accounts")
    print(f"Found {len(accounts)} manual accounts in Lunch Money\n")

    for account in accounts:
        account_id = account["id"]
        account_name = account.get("display_name") or account["name"]
        current_type = account.get("type", "unknown")

        has_numbers = bool(re.search(r"\d", account_name))
        new_type = "credit" if has_numbers else "cash"

        if current_type != new_type:
            print(f"Updating '{account_name}': {current_type} -> {new_type}")
            client.put(f"/manual_accounts/{account_id}", json={"type": new_type})
            print("  Updated successfully")
        else:
            print(f"'{account_name}': already {current_type} (no change)")


if __name__ == "__main__":
    print("Updating Lunch Money account types...")
    print("Rule: Accounts with numbers -> credit, others -> cash\n")
    try:
        update_account_types()
    except LunchMoneyAPIError as exc:
        print(f"Update failed: {exc}")
        raise SystemExit(1)
    print("\nDone!")
