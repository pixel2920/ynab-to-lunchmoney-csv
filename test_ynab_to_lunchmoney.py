#!/usr/bin/env python3
import os
import tempfile
import unittest

from ynab_to_lunchmoney import (
    build_lunch_money_transactions,
    create_lunch_money_transaction,
    get_primary_currency,
    process_transactions,
)


class YnabToLunchMoneyTest(unittest.TestCase):
    def test_process_transactions_and_build_v2_payloads(self):
        csv_text = "\n".join(
            [
                "Account,Flag,Date,Payee,Category Group,Category,Memo,Outflow,Inflow,Cleared",
                "Checking,Blue,01/02/2024,Coffee,Everyday,Dining,Latte,$4.50,,Cleared",
                "Checking,,02/02/2024,Paycheck,Income,Salary,,,$100.00,Uncleared",
                "Checking,,03/02/2024,Transfer : Savings,Internal,,Move,$25.00,,Cleared",
            ]
        )

        with tempfile.NamedTemporaryFile("w", delete=False, newline="") as tmp:
            tmp.write(csv_text)
            tmp_path = tmp.name

        try:
            transactions, transfer_pairs = process_transactions(tmp_path)
        finally:
            os.unlink(tmp_path)

        self.assertEqual(len(transactions), 3)
        self.assertEqual(len(transfer_pairs), 1)

        payloads = build_lunch_money_transactions(
            transactions,
            {"Checking": 10},
            {"Dining": 20, "_transfer": 21},
            {"Blue": 30},
            "usd",
        )

        self.assertEqual(payloads[0]["manual_account_id"], 10)
        self.assertEqual(payloads[0]["category_id"], 20)
        self.assertEqual(payloads[0]["tag_ids"], [30])
        self.assertEqual(payloads[0]["amount"], 4.5)
        self.assertEqual(payloads[0]["status"], "reviewed")
        self.assertEqual(payloads[1]["amount"], -100.0)
        self.assertEqual(payloads[1]["status"], "unreviewed")
        self.assertEqual(payloads[2]["payee"], "Savings")
        self.assertEqual(payloads[2]["category_id"], 21)

    def test_create_lunch_money_transaction_uses_external_id(self):
        txn = {
            "account": "Checking",
            "date": "2024-02-01",
            "payee": "Coffee",
            "category": "Dining",
            "category_group": "Everyday",
            "memo": "",
            "amount": -4.5,
            "is_transfer": False,
            "flag": "",
            "cleared": "Cleared",
            "original_index": 123,
        }

        payload = create_lunch_money_transaction(txn, 1, currency="usd")
        self.assertEqual(payload["external_id"], "ynab-csv-123")
        self.assertIn("manual_account_id", payload)
        self.assertNotIn("asset_id", payload)

    def test_get_primary_currency_from_me_endpoint(self):
        class FakeClient:
            def get(self, path):
                self.path = path
                return {"primary_currency": "USD"}

        client = FakeClient()
        self.assertEqual(get_primary_currency(client), "usd")
        self.assertEqual(client.path, "/me")


if __name__ == "__main__":
    unittest.main()
