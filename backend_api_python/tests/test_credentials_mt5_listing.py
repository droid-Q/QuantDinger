import inspect
import unittest
from unittest.mock import patch

from flask import Flask, g

from app.routes import credentials as credentials_routes


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _query, _params):
        return None

    def fetchall(self):
        return self._rows

    def close(self):
        return None


class _Connection:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def cursor(self):
        return _Cursor(self._rows)


class CredentialsMt5ListingTest(unittest.TestCase):
    def test_list_credentials_includes_mt5_accounts(self):
        rows = []
        for index, exchange_id in enumerate(
            ["mt5", "cptmarkets", "cpt_markets", "unsupported"],
            start=1,
        ):
            rows.append(
                {
                    "id": index,
                    "user_id": 1,
                    "name": exchange_id,
                    "exchange_id": exchange_id,
                    "api_key_hint": "89958589@CPTMarkets-Live",
                    "encrypted_config": None,
                    "created_at": None,
                    "updated_at": None,
                }
            )

        app = Flask(__name__)
        with patch.object(
            credentials_routes,
            "get_db_connection",
            return_value=_Connection(rows),
        ):
            with app.test_request_context("/api/credentials/list"):
                g.user_id = 1
                response = inspect.unwrap(credentials_routes.list_credentials)()

        body = response.get_json()
        exchange_ids = {item["exchange_id"] for item in body["data"]["items"]}

        self.assertEqual(body["code"], 1)
        self.assertEqual(exchange_ids, {"mt5", "cptmarkets", "cpt_markets"})
