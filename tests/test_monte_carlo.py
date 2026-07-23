import csv
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from monte_carlo import (  # noqa: E402
    Purse,
    assign_purse_odds,
    load_odds,
    simulate,
    write_results,
)


def purse(purse_id: str, msrp: float, tier: str = "Icon") -> Purse:
    return Purse(
        id=purse_id,
        name=f"Purse {purse_id}",
        brand="Brand",
        edit="New York",
        tier=tier,
        msrp=msrp,
        buyback_offer=msrp * 0.7,
        starting_inventory=1,
    )


class OddsTests(unittest.TestCase):
    def test_purses_split_tier_odds_equally_and_share_return_rate(self):
        purses = [purse("1", 100), purse("2", 200)]

        warnings = assign_purse_odds(
            purses,
            {"icon": 1.0},
            {"icon": "100-200"},
            {"icon": 0.65},
        )

        self.assertEqual(warnings, [])
        self.assertAlmostEqual(purses[0].purse_odds, 0.5)
        self.assertAlmostEqual(purses[1].purse_odds, 0.5)
        self.assertAlmostEqual(purses[0].return_rate, 0.65)
        self.assertAlmostEqual(purses[1].return_rate, 0.65)

    def test_odds_csv_reads_tier_return_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "odds.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Tier", "Edit", "Price Range", "Odds", "Return Rate"])
                writer.writerow(["Icon", "New York", "100-200", "1.0", "40%"])

            odds, ranges, return_rates = load_odds(path, "new_york")

        self.assertEqual(odds, {"icon": 1.0})
        self.assertEqual(ranges, {"icon": "100-200"})
        self.assertEqual(return_rates, {"icon": 0.4})


class CashFlowTests(unittest.TestCase):
    def test_acquisition_cost_always_equals_price(self):
        item = purse("1", 125)

        self.assertEqual(item.unit_cost, 125)

    def test_deterministic_buyback_cash_flow(self):
        item = purse("1", 100)
        item.return_rate = 1.0
        item.buyback_offer = 30
        item.tier_odds = 1.0
        item.purse_odds = 1.0
        config = {
            "box_price": 100.0,
            "simulations": 5,
            "openings_per_simulation": 10,
            "confidence_level": 0.99,
            "seed": 1,
        }

        result = simulate([item], config)

        self.assertEqual(result["initial_inventory_cost"], 100.0)
        self.assertEqual(result["recommended_starting_cash"]["amount"], 100.0)
        self.assertEqual(result["operating_profit_distribution"]["mean"], 700.0)
        self.assertEqual(result["simulated_outcomes"]["buybacks_or_returns"], 50)
        self.assertEqual(result["simulated_outcomes"]["shipped_and_replenished"], 0)

    def test_deterministic_shipping_cash_flow(self):
        item = purse("1", 100)
        item.return_rate = 0.0
        item.starting_inventory = 2
        item.tier_odds = 1.0
        item.purse_odds = 1.0
        config = {
            "box_price": 100.0,
            "simulations": 5,
            "openings_per_simulation": 10,
            "confidence_level": 0.99,
            "seed": 1,
        }

        result = simulate([item], config)

        self.assertEqual(result["initial_inventory_cost"], 200.0)
        self.assertEqual(result["recommended_starting_cash"]["amount"], 200.0)
        self.assertEqual(result["operating_profit_distribution"]["mean"], 0.0)
        self.assertEqual(result["simulated_outcomes"]["buybacks_or_returns"], 0)
        self.assertEqual(result["simulated_outcomes"]["shipped_and_replenished"], 50)

    def test_results_csv_contains_capital_and_profit_summary(self):
        item = purse("1", 100)
        item.return_rate = 1.0
        item.tier_odds = 1.0
        item.purse_odds = 1.0
        config = {
            "box_price": 100.0,
            "simulations": 5,
            "openings_per_simulation": 10,
            "confidence_level": 0.99,
            "seed": 1,
        }
        result = simulate([item], config)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            write_results(output_dir, result)
            with (output_dir / "simulation_results.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["selected_edit"], "New York")
        self.assertEqual(float(row["recommended_starting_cash"]), 100.0)
        self.assertEqual(float(row["expected_operating_profit_per_opening"]), 30.0)
        self.assertEqual(float(row["probability_of_operating_loss"]), 0.0)


if __name__ == "__main__":
    unittest.main()
