import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

import aiohttp

import plugin as url_data


class Reply:
    def __init__(self, status, payload=None, headers=None):
        self.status, self.payload, self.headers = status, payload, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(SimpleNamespace(real_url="https://example.com"), (), status=self.status,
                                             headers=self.headers)

    async def json(self, content_type=None):
        return self.payload


class Session:
    closed = False

    def __init__(self, replies):
        self.replies, self.asked = list(replies), 0

    def get(self, url):
        self.asked += 1
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def provider(**settings):
    values = dict(url_data.defaults, **settings)
    links = url_data.Links(SimpleNamespace(settings=values))
    return links


class PollingTests(unittest.TestCase):
    def run_polls(self, links, session, clock, count=12, every=5):
        links.session = session
        snaps = []
        with mock.patch.object(url_data.time, "monotonic", side_effect=lambda: clock[0]):
            for _ in range(count):
                snaps.append(asyncio.run(links.fetch()))
                clock[0] += every
        return snaps

    def test_a_link_is_asked_once_per_refresh_not_on_every_poll(self):
        """RackTicker polls every 5 s; a 60 s refresh is 1 request a minute, not 12."""
        session = Session([Reply(200, {"bitcoin": {"usd": 64000, "usd_24h_change": 1.2}})])
        snaps = self.run_polls(provider(refresh_seconds=60), session, [1000.0])
        self.assertEqual(session.asked, 1)
        self.assertTrue(all(snap.data and snap.data[0]["value"] == "64,000" for snap in snaps))

    def test_too_many_requests_backs_off_and_keeps_the_last_value(self):
        good = Reply(200, {"bitcoin": {"usd": 64000}})
        busy = Reply(429, headers={"Retry-After": "300"})
        session = Session([good, busy, busy])
        clock = [1000.0]
        with mock.patch("builtins.print"):
            snaps = self.run_polls(provider(refresh_seconds=60), session, clock, count=60)  # five minutes
        # One good reply, one refusal at the next refresh, then silence for the 300 s asked for.
        self.assertEqual(session.asked, 2)
        self.assertTrue(all(snap.data for snap in snaps))

    def test_retry_after_grows_with_each_refusal(self):
        refusal = aiohttp.ClientResponseError(None, (), status=429, headers={})
        waits = [url_data.retry_after(refusal, n, 60) for n in (1, 2, 3)]
        self.assertEqual(waits, sorted(waits))
        self.assertGreater(waits[0], 60)
        self.assertLessEqual(url_data.retry_after(refusal, 50, 60), 3600)

    def test_a_changed_link_is_asked_straight_away(self):
        session = Session([Reply(200, {"a": 1})])
        links = provider(refresh_seconds=600, url_1="https://example.com/a", path_1="a", change_1="", detail_1="")
        self.run_polls(links, session, [1000.0], count=2)
        links.context.settings["url_1"] = "https://example.com/b"
        self.run_polls(links, session, [1010.0], count=1)
        self.assertEqual(session.asked, 2)


if __name__ == "__main__":
    unittest.main()
