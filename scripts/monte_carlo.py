#!/usr/bin/env python3
"""Monte Carlo working-capital simulator for Luxury Edits."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_CONFIG: dict[str, Any] = {
    "edit": "",
    "box_price": 100.0,
    "simulations": 10_000,
    "openings_per_simulation": 1_000,
    "confidence_level": 0.99,
    "seed": 20260723,
    "default_buyback_offer_rate": 0.70,
    "default_starting_inventory": 1,
}


@dataclass
class Purse:
    id: str
    name: str
    brand: str
    edit: str
    tier: str
    msrp: float
    buyback_offer: float
    starting_inventory: int
    return_rate: float = 0.0
    tier_odds: float = 0.0
    purse_odds: float = 0.0

    @property
    def unit_cost(self) -> float:
        """Acquisition and replenishment cost always equals the purse price."""
        return self.msrp

    @property
    def expected_cash_cost_if_drawn(self) -> float:
        return (
            self.return_rate * self.buyback_offer
            + (1.0 - self.return_rate) * self.unit_cost
        )


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def normalize_edit(value: Any) -> str:
    return normalize_key(value).removesuffix("_edit")


def normalized_row(row: dict[str, Any]) -> dict[str, str]:
    return {normalize_key(key): str(value or "").strip() for key, value in row.items()}


def first_present(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value != "":
            return value
    return ""


def parse_number(value: Any, field: str) -> float:
    text = str(value).strip().replace("$", "").replace(",", "")
    try:
        number = float(text)
    except ValueError as error:
        raise ValueError(f"{field} must be a number; received {value!r}.") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite.")
    return number


def parse_rate(value: Any, field: str) -> float:
    text = str(value).strip()
    if text.endswith("%"):
        rate = parse_number(text[:-1], field) / 100.0
    else:
        rate = parse_number(text, field)
    if not 0.0 <= rate <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1; received {rate}.")
    return rate


def parse_nonnegative_integer(value: Any, field: str) -> int:
    number = parse_number(value, field)
    if number < 0 or not number.is_integer():
        raise ValueError(f"{field} must be a non-negative whole number.")
    return int(number)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        return [normalized_row(row) for row in reader]


def require_columns(
    rows: list[dict[str, str]], required: set[str], label: str
) -> None:
    if not rows:
        raise ValueError(f"{label} contains no data rows.")
    missing = sorted(required - set(rows[0]))
    if missing:
        raise ValueError(f"{label} is missing column(s): {', '.join(missing)}")


def read_config(path: Path | None) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if path is None:
        return config
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        supplied = json.load(handle)
    if not isinstance(supplied, dict):
        raise ValueError("Configuration JSON must contain one object.")
    unknown = sorted(set(supplied) - set(DEFAULT_CONFIG))
    if unknown:
        raise ValueError(f"Unknown configuration field(s): {', '.join(unknown)}")
    config.update(supplied)
    return config


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    validated = dict(config)
    validated["edit"] = str(config.get("edit", "")).strip()
    validated["box_price"] = parse_number(config["box_price"], "box_price")
    validated["simulations"] = parse_nonnegative_integer(
        config["simulations"], "simulations"
    )
    validated["openings_per_simulation"] = parse_nonnegative_integer(
        config["openings_per_simulation"], "openings_per_simulation"
    )
    validated["confidence_level"] = parse_rate(
        config["confidence_level"], "confidence_level"
    )
    validated["seed"] = int(parse_number(config["seed"], "seed"))
    validated["default_buyback_offer_rate"] = parse_rate(
        config["default_buyback_offer_rate"], "default_buyback_offer_rate"
    )
    validated["default_starting_inventory"] = parse_nonnegative_integer(
        config["default_starting_inventory"], "default_starting_inventory"
    )
    if validated["box_price"] < 0:
        raise ValueError("box_price cannot be negative.")
    if validated["simulations"] < 1:
        raise ValueError("simulations must be at least 1.")
    if validated["openings_per_simulation"] < 1:
        raise ValueError("openings_per_simulation must be at least 1.")
    if not 0.5 <= validated["confidence_level"] < 1.0:
        raise ValueError("confidence_level must be at least 0.5 and below 1.")
    return validated


def load_odds(
    path: Path, selected_edit: str
) -> tuple[dict[str, float], dict[str, str], dict[str, float]]:
    odds_by_tier: dict[str, float] = {}
    ranges_by_tier: dict[str, str] = {}
    return_rates_by_tier: dict[str, float] = {}
    for line_number, row in enumerate(read_csv(path), start=2):
        edit = normalize_edit(first_present(row, "edit"))
        if edit != selected_edit:
            continue
        tier_name = first_present(row, "tier")
        tier = normalize_key(tier_name)
        if not tier:
            raise ValueError(f"Odds row {line_number} is missing tier.")
        if tier in odds_by_tier:
            raise ValueError(f"Duplicate odds tier for selected edit: {tier_name}")
        odds_by_tier[tier] = parse_rate(first_present(row, "odds"), f"odds row {line_number}")
        ranges_by_tier[tier] = first_present(row, "price_range", "price range")
        return_rate = first_present(row, "return_rate", "return rate")
        if not return_rate:
            raise ValueError(
                f"Odds row {line_number} is missing Return Rate for tier {tier_name!r}."
            )
        return_rates_by_tier[tier] = parse_rate(
            return_rate, f"return rate row {line_number}"
        )
    if not odds_by_tier:
        raise ValueError(f"No odds rows found for edit {selected_edit!r}.")
    total = sum(odds_by_tier.values())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Tier odds for the selected edit sum to {total:.12f}, not 1.0.")
    return odds_by_tier, ranges_by_tier, return_rates_by_tier


def choose_edit(
    purse_rows: list[dict[str, str]],
    odds_rows: list[dict[str, str]],
    requested_edit: str,
) -> str:
    if requested_edit:
        return normalize_edit(requested_edit)
    purse_edits = {
        normalize_edit(first_present(row, "edit"))
        for row in purse_rows
        if first_present(row, "edit")
    }
    odds_edits = {
        normalize_edit(first_present(row, "edit"))
        for row in odds_rows
        if first_present(row, "edit")
    }
    shared = sorted(purse_edits & odds_edits)
    if len(shared) == 1:
        return shared[0]
    if not shared:
        raise ValueError("The purse and odds CSVs do not contain a shared edit.")
    raise ValueError(
        "Multiple edits are available. Set edit in the config or pass --edit. "
        f"Choices: {', '.join(shared)}"
    )


def load_purses(
    purse_rows: list[dict[str, str]],
    selected_edit: str,
    config: dict[str, Any],
) -> list[Purse]:
    purses: list[Purse] = []
    seen_ids: set[str] = set()
    for line_number, original in enumerate(purse_rows, start=2):
        if normalize_edit(first_present(original, "edit")) != selected_edit:
            continue
        purse_id = first_present(original, "id", "purse_id")
        if not purse_id:
            raise ValueError(f"Purse row {line_number} is missing id.")
        if purse_id in seen_ids:
            raise ValueError(f"Duplicate purse id for selected edit: {purse_id}")
        seen_ids.add(purse_id)
        name = first_present(original, "name")
        brand = first_present(original, "brand")
        tier = first_present(original, "tier")
        if not name or not brand or not tier:
            raise ValueError(
                f"Purse row {line_number} requires name, brand/designer, and tier."
            )
        msrp = parse_number(first_present(original, "price"), f"price for purse {purse_id}")
        if msrp < 0:
            raise ValueError(f"MSRP cannot be negative for purse {purse_id}.")
        buyback_offer = msrp * config["default_buyback_offer_rate"]
        starting_inventory = config["default_starting_inventory"]
        purses.append(
            Purse(
                id=purse_id,
                name=name,
                brand=brand,
                edit=first_present(original, "edit"),
                tier=tier,
                msrp=msrp,
                buyback_offer=buyback_offer,
                starting_inventory=starting_inventory,
            )
        )
    if not purses:
        raise ValueError(f"No purses found for edit {selected_edit!r}.")
    return purses


def parse_price_range(value: str) -> tuple[float, float] | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*", value)
    if not match:
        return None
    lower_text, upper_text = match.groups()
    lower = float(lower_text)
    upper = float(upper_text)
    # A sheet range such as 45-99 conventionally includes prices through $99.99.
    if "." not in upper_text:
        upper += 0.999999
    return lower, upper


def assign_purse_odds(
    purses: list[Purse],
    odds_by_tier: dict[str, float],
    ranges_by_tier: dict[str, str],
    return_rates_by_tier: dict[str, float],
) -> list[str]:
    by_tier: dict[str, list[Purse]] = {}
    for purse in purses:
        by_tier.setdefault(normalize_key(purse.tier), []).append(purse)
    missing_purse_tiers = sorted(set(by_tier) - set(odds_by_tier))
    empty_odds_tiers = sorted(set(odds_by_tier) - set(by_tier))
    if missing_purse_tiers:
        raise ValueError(
            "Purse tiers missing from the odds CSV: " + ", ".join(missing_purse_tiers)
        )
    if empty_odds_tiers:
        raise ValueError(
            "Odds tiers with no eligible purses: " + ", ".join(empty_odds_tiers)
        )
    warnings: list[str] = []
    for tier, tier_purses in by_tier.items():
        tier_odds = odds_by_tier[tier]
        purse_odds = tier_odds / len(tier_purses)
        price_range = parse_price_range(ranges_by_tier.get(tier, ""))
        for purse in tier_purses:
            purse.tier_odds = tier_odds
            purse.purse_odds = purse_odds
            purse.return_rate = return_rates_by_tier[tier]
            if price_range and not price_range[0] <= purse.msrp <= price_range[1]:
                warnings.append(
                    f"{purse.id} ({purse.name}) has MSRP ${purse.msrp:,.2f}, "
                    f"outside {purse.tier} range {price_range[0]:g}-{price_range[1]:g}."
                )
    total = sum(purse.purse_odds for purse in purses)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Calculated purse odds sum to {total:.12f}, not 1.0.")
    return warnings


def percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("Cannot calculate a percentile from an empty list.")
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def money(value: float) -> float:
    return round(value + 1e-12, 2)


def distribution(values: Iterable[float], confidence_level: float) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": money(sum(ordered) / len(ordered)),
        "p01": money(percentile(ordered, 0.01)),
        "p05": money(percentile(ordered, 0.05)),
        "p50": money(percentile(ordered, 0.50)),
        "p90": money(percentile(ordered, 0.90)),
        "p95": money(percentile(ordered, 0.95)),
        "p99": money(percentile(ordered, 0.99)),
        "configured_confidence": money(percentile(ordered, confidence_level)),
        "maximum": money(ordered[-1]),
        "minimum": money(ordered[0]),
    }


def simulate(purses: list[Purse], config: dict[str, Any]) -> dict[str, Any]:
    rng = random.Random(config["seed"])
    cumulative_odds: list[float] = []
    running_odds = 0.0
    for purse in purses:
        running_odds += purse.purse_odds
        cumulative_odds.append(running_odds)
    cumulative_odds[-1] = 1.0

    initial_inventory_cost = sum(
        purse.unit_cost * purse.starting_inventory for purse in purses
    )
    required_capital: list[float] = []
    operating_profits: list[float] = []
    ending_cash_changes: list[float] = []
    observed_counts = [0] * len(purses)
    buyback_count = 0
    shipped_count = 0

    for _ in range(config["simulations"]):
        cash = -initial_inventory_cost
        minimum_cash = cash
        for _ in range(config["openings_per_simulation"]):
            purse_index = bisect.bisect_left(cumulative_odds, rng.random())
            purse = purses[purse_index]
            observed_counts[purse_index] += 1
            cash += config["box_price"]
            if rng.random() < purse.return_rate:
                cash -= purse.buyback_offer
                buyback_count += 1
            else:
                cash -= purse.unit_cost
                shipped_count += 1
            minimum_cash = min(minimum_cash, cash)
        required_capital.append(max(0.0, -minimum_cash))
        ending_cash_changes.append(cash)
        operating_profits.append(cash + initial_inventory_cost)

    total_openings = config["simulations"] * config["openings_per_simulation"]
    expected_msrp = sum(purse.purse_odds * purse.msrp for purse in purses)
    expected_cash_cost = sum(
        purse.purse_odds * purse.expected_cash_cost_if_drawn for purse in purses
    )
    expected_profit = config["box_price"] - expected_cash_cost
    confidence = config["confidence_level"]
    capital_distribution = distribution(required_capital, confidence)
    recommended_capital = capital_distribution["configured_confidence"]

    purse_results: list[dict[str, Any]] = []
    for index, purse in enumerate(purses):
        row = asdict(purse)
        row.update(
            {
                "unit_cost": purse.unit_cost,
                "one_in": round(1.0 / purse.purse_odds, 4),
                "expected_cash_cost_if_drawn": money(
                    purse.expected_cash_cost_if_drawn
                ),
                "expected_cost_contribution_per_box": money(
                    purse.purse_odds * purse.expected_cash_cost_if_drawn
                ),
                "observed_draws": observed_counts[index],
                "observed_odds": observed_counts[index] / total_openings,
            }
        )
        purse_results.append(row)

    return {
        "model": {
            "return_rate_definition": (
                "Probability the customer accepts instant buyback/returns the piece "
                "to the platform. The platform pays buyback_offer and retains the item."
            ),
            "ship_definition": (
                "If buyback is not accepted, the item ships and is immediately "
                "replenished at the purse CSV price."
            ),
            "acquisition_cost_definition": (
                "Acquisition and replenishment cost equals the purse CSV price exactly."
            ),
            "capital_definition": (
                "Initial inventory purchase plus enough cash to prevent the simulated "
                "cash balance from falling below zero."
            ),
            "revenue_timing": "Box revenue is collected before fulfillment cash outflow.",
            "taxes_fees_shipping_included": False,
        },
        "config": config,
        "selected_edit": purses[0].edit,
        "purse_count": len(purses),
        "total_simulated_openings": total_openings,
        "initial_inventory_cost": money(initial_inventory_cost),
        "expected_per_opening": {
            "box_revenue": money(config["box_price"]),
            "prize_msrp": money(expected_msrp),
            "fulfillment_cash_cost": money(expected_cash_cost),
            "operating_profit": money(expected_profit),
            "operating_margin": (
                round(expected_profit / config["box_price"], 6)
                if config["box_price"]
                else None
            ),
            "break_even_box_price": money(expected_cash_cost),
        },
        "recommended_starting_cash": {
            "confidence_level": confidence,
            "amount": recommended_capital,
        },
        "required_starting_cash_distribution": capital_distribution,
        "operating_profit_distribution": distribution(operating_profits, confidence),
        "ending_cash_change_distribution": distribution(ending_cash_changes, confidence),
        "probability_of_operating_loss": round(
            sum(value < 0 for value in operating_profits) / len(operating_profits), 6
        ),
        "simulated_outcomes": {
            "buybacks_or_returns": buyback_count,
            "shipped_and_replenished": shipped_count,
            "observed_return_rate": round(buyback_count / total_openings, 6),
        },
        "purses": purse_results,
    }


def write_results(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "simulation_summary.json"
    with summary_path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")

    config = result["config"]
    expected = result["expected_per_opening"]
    capital = result["required_starting_cash_distribution"]
    profit = result["operating_profit_distribution"]
    ending_cash = result["ending_cash_change_distribution"]
    results_row = {
        "selected_edit": result["selected_edit"],
        "simulations": config["simulations"],
        "openings_per_simulation": config["openings_per_simulation"],
        "total_simulated_openings": result["total_simulated_openings"],
        "purse_count": result["purse_count"],
        "box_price": expected["box_revenue"],
        "initial_inventory_cost": result["initial_inventory_cost"],
        "expected_prize_msrp": expected["prize_msrp"],
        "expected_fulfillment_cash_cost": expected["fulfillment_cash_cost"],
        "expected_operating_profit_per_opening": expected["operating_profit"],
        "expected_operating_margin": expected["operating_margin"],
        "break_even_box_price": expected["break_even_box_price"],
        "confidence_level": result["recommended_starting_cash"]["confidence_level"],
        "recommended_starting_cash": result["recommended_starting_cash"]["amount"],
        "required_cash_p50": capital["p50"],
        "required_cash_p90": capital["p90"],
        "required_cash_p95": capital["p95"],
        "required_cash_p99": capital["p99"],
        "required_cash_maximum": capital["maximum"],
        "operating_profit_mean": profit["mean"],
        "operating_profit_p05": profit["p05"],
        "operating_profit_p50": profit["p50"],
        "operating_profit_minimum": profit["minimum"],
        "ending_cash_change_mean": ending_cash["mean"],
        "probability_of_operating_loss": result["probability_of_operating_loss"],
        "observed_return_rate": result["simulated_outcomes"]["observed_return_rate"],
        "seed": config["seed"],
    }
    results_path = output_dir / "simulation_results.csv"
    with results_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results_row))
        writer.writeheader()
        writer.writerow(results_row)

    odds_path = output_dir / "purse_odds.csv"
    fields = [
        "id",
        "brand",
        "name",
        "tier",
        "msrp",
        "tier_odds",
        "purse_odds",
        "one_in",
        "unit_cost",
        "return_rate",
        "buyback_offer",
        "starting_inventory",
        "expected_cash_cost_if_drawn",
        "expected_cost_contribution_per_box",
        "observed_draws",
        "observed_odds",
    ]
    with odds_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["purses"])


def print_report(result: dict[str, Any], output_dir: Path | None) -> None:
    config = result["config"]
    expected = result["expected_per_opening"]
    capital = result["required_starting_cash_distribution"]
    recommended = result["recommended_starting_cash"]
    profit = result["operating_profit_distribution"]

    print(f"\nLuxury Edits Monte Carlo - {result['selected_edit']}")
    print(
        f"{config['simulations']:,} simulations x "
        f"{config['openings_per_simulation']:,} openings "
        f"({result['total_simulated_openings']:,} total draws)"
    )
    print(f"Calculated purse odds: {result['purse_count']} purses")
    print(f"Initial inventory investment: ${result['initial_inventory_cost']:,.2f}")
    print("\nExpected per opening")
    print(f"  Box revenue:               ${expected['box_revenue']:>12,.2f}")
    print(f"  Prize MSRP:                ${expected['prize_msrp']:>12,.2f}")
    print(f"  Fulfillment cash cost:     ${expected['fulfillment_cash_cost']:>12,.2f}")
    print(f"  Operating profit:          ${expected['operating_profit']:>12,.2f}")
    print(f"  Break-even box price:      ${expected['break_even_box_price']:>12,.2f}")
    print("\nRequired starting cash")
    print(f"  50th percentile:           ${capital['p50']:>12,.2f}")
    print(f"  90th percentile:           ${capital['p90']:>12,.2f}")
    print(f"  95th percentile:           ${capital['p95']:>12,.2f}")
    print(f"  99th percentile:           ${capital['p99']:>12,.2f}")
    print(
        f"  Recommended ({recommended['confidence_level']:.1%}): "
        f"${recommended['amount']:,.2f}"
    )
    print("\nOperating profit over each simulated horizon")
    print(f"  Mean:                      ${profit['mean']:>12,.2f}")
    print(f"  5th percentile:            ${profit['p05']:>12,.2f}")
    print(f"  Minimum:                   ${profit['minimum']:>12,.2f}")
    print(
        f"  Probability of loss:       "
        f"{result['probability_of_operating_loss']:.2%}"
    )
    if output_dir is not None:
        print(f"\nWrote {output_dir / 'simulation_summary.json'}")
        print(f"Wrote {output_dir / 'simulation_results.csv'}")
        print(f"Wrote {output_dir / 'purse_odds.csv'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate per-purse odds and simulate the working capital required "
            "to operate a Luxury Edits box."
        )
    )
    parser.add_argument("--purses", required=True, type=Path, help="Purse catalog CSV")
    parser.add_argument("--odds", required=True, type=Path, help="Tier odds CSV")
    parser.add_argument("--config", type=Path, help="Simulation configuration JSON")
    parser.add_argument("--edit", help="Edit to simulate, such as 'New York'")
    parser.add_argument("--box-price", type=float, help="Override box price")
    parser.add_argument("--simulations", type=int, help="Override simulation count")
    parser.add_argument("--openings", type=int, help="Override openings per simulation")
    parser.add_argument("--confidence", type=float, help="Override confidence level")
    parser.add_argument("--seed", type=int, help="Override random seed")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("simulation-results"),
        help="Directory for summary JSON and calculated purse odds CSV",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Print the report without writing result files",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        cli_values = {
            "edit": args.edit,
            "box_price": args.box_price,
            "simulations": args.simulations,
            "openings_per_simulation": args.openings,
            "confidence_level": args.confidence,
            "seed": args.seed,
        }
        config.update(
            {key: value for key, value in cli_values.items() if value is not None}
        )
        config = validate_config(config)
        purse_rows = read_csv(args.purses)
        odds_rows = read_csv(args.odds)
        require_columns(
            purse_rows,
            {"id", "name", "price", "brand", "edit", "tier", "image_name"},
            "Purse CSV",
        )
        require_columns(
            odds_rows,
            {"tier", "edit", "price_range", "odds", "return_rate"},
            "Odds CSV",
        )
        selected_edit = choose_edit(purse_rows, odds_rows, config["edit"])
        odds_by_tier, ranges_by_tier, return_rates_by_tier = load_odds(
            args.odds, selected_edit
        )
        purses = load_purses(purse_rows, selected_edit, config)
        warnings = assign_purse_odds(
            purses,
            odds_by_tier,
            ranges_by_tier,
            return_rates_by_tier,
        )
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        result = simulate(purses, config)
        result["warnings"] = warnings
        output_dir = None if args.no_output else args.output_dir
        if output_dir is not None:
            write_results(output_dir, result)
        print_report(result, output_dir)
        return 0
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
