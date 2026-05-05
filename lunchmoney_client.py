#!/usr/bin/env python3
import os
import random
import time

class LunchMoneyAPIError(Exception):
    """Raised when the Lunch Money API returns an unrecoverable error."""


class LunchMoneyClient:
    def __init__(self, token=None, base_url=None, min_remaining=None, max_retries=None):
        self.token = token or os.getenv("LUNCHMONEY_TOKEN")
        self.base_url = (base_url or os.getenv("LUNCHMONEY_BASE_URL") or "https://api.lunchmoney.dev/v2").rstrip("/")
        self.min_remaining = int(os.getenv("LUNCHMONEY_RATE_LIMIT_BUFFER", min_remaining or 5))
        self.max_retries = int(os.getenv("LUNCHMONEY_MAX_RETRIES", max_retries or 5))

        if not self.token:
            raise LunchMoneyAPIError("Missing LUNCHMONEY_TOKEN environment variable.")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)

    def request(self, method, path, expected_statuses=None, **kwargs):
        try:
            import requests
        except ImportError as exc:
            raise LunchMoneyAPIError("Missing requests dependency. Install it with: pip install requests") from exc

        expected_statuses = expected_statuses or {200, 201, 204}
        url = f"{self.base_url}/{path.lstrip('/')}"

        for attempt in range(self.max_retries + 1):
            response = requests.request(method, url, headers=self.headers, **kwargs)

            if response.status_code == 429:
                if attempt == self.max_retries:
                    raise LunchMoneyAPIError(f"Rate limited and retries exhausted: {response.text}")
                self._sleep_for_retry(response, attempt)
                continue

            if response.status_code not in expected_statuses:
                raise LunchMoneyAPIError(
                    f"{method} {path} failed with {response.status_code}: {response.text[:500]}"
                )

            self._sleep_if_quota_low(response)
            if response.status_code == 204 or not response.text:
                return None
            return response.json()

        raise LunchMoneyAPIError(f"{method} {path} failed after retries.")

    def _sleep_for_retry(self, response, attempt):
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            wait_seconds = int(float(retry_after))
        else:
            wait_seconds = self._seconds_until_reset(response)
            if wait_seconds <= 0:
                wait_seconds = min(60, 2**attempt)

        wait_seconds += random.uniform(0, 1)
        print(f"Rate limited. Waiting {wait_seconds:.1f}s before retrying...")
        time.sleep(wait_seconds)

    def _sleep_if_quota_low(self, response):
        remaining = self._header_int(response, "RateLimit-Remaining", "X-RateLimit-Remaining")
        if remaining is None or remaining > self.min_remaining:
            return

        wait_seconds = self._seconds_until_reset(response)
        if wait_seconds > 0:
            wait_seconds += 1
            print(f"Rate limit nearly exhausted ({remaining} remaining). Waiting {wait_seconds}s...")
            time.sleep(wait_seconds)

    def _seconds_until_reset(self, response):
        reset = self._header_int(response, "RateLimit-Reset", "X-RateLimit-Reset")
        if reset is None:
            return 0
        return max(0, reset - int(time.time()))

    @staticmethod
    def _header_int(response, *names):
        for name in names:
            value = response.headers.get(name)
            if value:
                try:
                    return int(float(value))
                except ValueError:
                    return None
        return None


def extract_list(payload, key):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []
