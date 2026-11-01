"""Tests for the small HenrikDev HTTP client (network calls are mocked)."""
import io
import json
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError

from valorant.henrik import HenrikClient, HenrikError, _payload_error, _safe_float


def _response(payload):
    raw = json.dumps(payload).encode("utf-8")

    class Response:
        status = 200

        def read(self):
            return raw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return Response()


class ClientRequestTests(unittest.TestCase):
    def client(self, **kwargs):
        return HenrikClient("test-key", min_interval=0, **kwargs)

    def test_missing_key_fails_without_a_request(self):
        with mock.patch("valorant.henrik.urlopen") as urlopen:
            with self.assertRaises(HenrikError) as ctx:
                HenrikClient("", min_interval=0).account("TenZ", "NA1")
        urlopen.assert_not_called()
        self.assertEqual(ctx.exception.status, 401)

    def test_authorization_header_and_url_are_built(self):
        with mock.patch("valorant.henrik.urlopen", return_value=_response({"status": 200, "data": []})) as urlopen:
            self.client().matches("eu", "pc", "JoueurTest", "TEST", start=20, size=10, mode=None)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "test-key")
        self.assertIn("/valorant/v4/matches/eu/pc/JoueurTest/TEST", request.full_url)
        self.assertIn("start=20", request.full_url)
        self.assertIn("size=10", request.full_url)
        self.assertNotIn("mode=", request.full_url)

    def test_special_characters_are_quoted(self):
        with mock.patch("valorant.henrik.urlopen", return_value=_response({"status": 200, "data": {}})) as urlopen:
            self.client().account("nom bizarre", "tag/1")
        url = urlopen.call_args[0][0].full_url
        self.assertIn("nom%20bizarre", url)
        self.assertIn("tag%2F1", url)

    def test_mmr_history_endpoint_unwraps_the_history(self):
        payload = {"status": 200, "data": {"history": [{"match_id": "m1", "elo": 1500}]}}
        with mock.patch("valorant.henrik.urlopen", return_value=_response(payload)) as urlopen:
            history = self.client().mmr_history("eu", "pc", "JoueurTest", "TEST")
        request = urlopen.call_args[0][0]
        self.assertIn("/valorant/v2/mmr-history/eu/pc/JoueurTest/TEST", request.full_url)
        self.assertEqual(history, [{"match_id": "m1", "elo": 1500}])

    def test_payload_status_error_is_raised(self):
        payload = {"status": 400, "errors": [{"message": "Invalid region"}]}
        with mock.patch("valorant.henrik.urlopen", return_value=_response(payload)):
            with self.assertRaises(HenrikError) as ctx:
                self.client().account("JoueurTest", "TEST")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("Invalid region", str(ctx.exception))


class ClientErrorTests(unittest.TestCase):
    def test_401_message_mentions_the_key(self):
        error = HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        with mock.patch("valorant.henrik.urlopen", side_effect=error):
            with self.assertRaises(HenrikError) as ctx:
                HenrikClient("key", min_interval=0).account("JoueurTest", "TEST")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("Clé API", ctx.exception.message)

    def test_404_message_mentions_the_riot_id(self):
        error = HTTPError("https://x", 404, "Not Found", {}, io.BytesIO(b"{}"))
        with mock.patch("valorant.henrik.urlopen", side_effect=error):
            with self.assertRaises(HenrikError) as ctx:
                HenrikClient("key", min_interval=0).account("JoueurTest", "TEST")
        self.assertIn("Riot ID", ctx.exception.message)

    def test_network_errors_are_retried_then_reported(self):
        with mock.patch("valorant.henrik.urlopen", side_effect=URLError("offline")), mock.patch(
            "valorant.henrik.time.sleep"
        ) as sleep:
            with self.assertRaises(HenrikError) as ctx:
                HenrikClient("key", min_interval=0).account("JoueurTest", "TEST")
        self.assertIn("connexion", ctx.exception.message.lower())
        self.assertGreater(sleep.call_count, 0)

    def test_rate_limit_waits_and_retries(self):
        error = HTTPError("https://x", 429, "Too Many Requests", {"Retry-After": "0"}, io.BytesIO(b"{}"))
        with mock.patch(
            "valorant.henrik.urlopen", side_effect=[error, _response({"status": 200, "data": {"ok": True}})],
        ), mock.patch("valorant.henrik.time.sleep"):
            data = HenrikClient("key", min_interval=0).account("JoueurTest", "TEST")
        self.assertEqual(data, {"ok": True})


class HelperTests(unittest.TestCase):
    def test_payload_error_prefers_details(self):
        payload = {
            "errors": [
                {"message": "Rate limited", "details": {"message": "Slow down"}},
            ]
        }
        self.assertEqual(_payload_error(payload), "Rate limited (Slow down)")

    def test_payload_error_falls_back_to_message(self):
        self.assertEqual(_payload_error({"message": "Nope"}), "Nope")
        self.assertEqual(_payload_error({}), "")

    def test_safe_float(self):
        self.assertEqual(_safe_float("2.5", 1.0), 2.5)
        self.assertEqual(_safe_float(None, 4.0), 4.0)
        self.assertEqual(_safe_float("abc", 4.0), 4.0)


if __name__ == "__main__":
    unittest.main()
