from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

import plugin as chain

ROWS = [{"height": 971019 - i, "timestamp": 1791767641 - i * 600, "tx_count": 6000 + i, "weight": 3990000,
         "extras": {"reward": 312958259, "totalFees": 458259, "pool": {"name": "Binance Pool"}}} for i in range(8)]


def context(ts, data, t=0.0):
    return SimpleNamespace(now=datetime.fromtimestamp(ts, timezone.utc), animation_time=t, scene=1,
                           config={"display": {"fps": 30}, "plugins": {"blocks": {"alert": False}}},
                           snapshots={"blocks": SimpleNamespace(data=data)})


class BlockTests(unittest.TestCase):
    def test_parse_orders_oldest_first(self):
        blocks = chain.parse_blocks(ROWS)
        self.assertEqual([block["height"] for block in blocks], sorted(row["height"] for row in ROWS))
        self.assertAlmostEqual(blocks[-1]["reward"], 3.12958259)
        self.assertEqual(blocks[-1]["pool"], "Binance Pool")

    def test_cards_and_arrival(self):
        data = {"blocks": chain.parse_blocks(ROWS), "waiting": 72000, "vsize": 37.8e6, "fee": 2, "slow_fee": 1}
        module = chain.Blocks()
        later = ROWS[0]["timestamp"] + 600
        frames = {module.render(context(later, data, t)).tobytes() for t in (0, 5, 10, 13, 18, 22, 26)}
        self.assertGreaterEqual(len(frames), 4)
        arrival = module.render(context(ROWS[0]["timestamp"] + 2, data, 1.5))
        self.assertIsNotNone(arrival.getbbox())
        self.assertFalse(module.available(context(later, {})))


if __name__ == "__main__":
    unittest.main()
