# Luxury Edits Monte Carlo simulator

The simulator uses exactly two CSV inputs:

1. A purse catalog with every eligible purse.
2. A tier table with odds and return rates.

It calculates each purse's probability and estimates the starting cash needed
over a selected number of simulated box openings. It uses only Python's
standard library.

## Run it

```powershell
python scripts/monte_carlo.py `
  --purses "C:\path\to\purses.csv" `
  --odds "C:\path\to\odds.csv" `
  --output-dir simulation-results
```

Those are the only two CSV inputs. The optional
`--config data/simulation-config.example.json` argument can be added when you
want to change the simulation assumptions.

The command writes:

- `simulation_summary.json`: assumptions, capital percentiles, expected
  economics, and complete results.
- `simulation_results.csv`: one spreadsheet-ready summary row with the run
  inputs, expected economics, starting-cash percentiles, profit percentiles,
  loss probability, and observed return rate.
- `purse_odds.csv`: calculated odds and tier return rate for every purse.

## Run in GitHub Actions

The **Run Monte Carlo simulator** workflow can be started from the repository's
**Actions** tab using **Run workflow**.

1. Commit the purse and odds CSV exports to the repository.
2. Open **Actions → Run Monte Carlo simulator → Run workflow**.
3. Enter their repository paths, such as `data/bags.csv` and `data/odds.csv`.
4. Adjust the box price, simulations, openings, confidence level, or seed.
5. Download the `luxury-edits-monte-carlo-*` artifact when the run finishes.

The artifact contains `simulation_results.csv`, `purse_odds.csv`, and the
detailed `simulation_summary.json`. The summary CSV is also displayed directly
on the workflow run page.

## Purse CSV

The required schema is:

```csv
id,name,price,brand,edit,tier,image_name
1,Example Bag,125,Example Brand,New York,Runway,example.webp
```

`price` is the MSRP in dollars. The simulator assumes acquisition and
replenishment cost equals `price` exactly.

## Odds CSV

The required schema is:

```csv
Tier,Edit,Price Range,Odds,Return Rate
Runway,New York,125-159,0.23,0.45
```

- `Odds` is the probability of drawing the tier.
- `Return Rate` is the probability that a customer accepts instant buyback and
  the purse returns to Luxury Edits.
- Rates may be decimals such as `0.45` or percentages such as `45%`.
- Tier odds must sum to exactly `1.0` for the selected edit.
- Every purse in a tier receives the same return rate.
- Every purse in a tier receives an equal share of that tier's odds.

For example, if Runway has 23% odds and contains five purses, each purse has
`23% / 5 = 4.6%` odds.

## Cash-flow model

For each opening:

1. The customer pays `box_price`.
2. A tier is selected using the odds CSV.
3. A purse is selected with equal probability from that tier.
4. With the tier's `Return Rate`, the customer accepts instant buyback. Luxury
   Edits pays `price × default_buyback_offer_rate` and keeps the purse.
5. Otherwise, the purse ships and is immediately replenished for its full
   `price`.

The simulation starts by purchasing `default_starting_inventory` units of every
purse at full price. Required starting cash is the amount that would have kept
the simulated cash balance from becoming negative. The configured confidence
level selects the recommendation; `0.99` covers 99% of simulated runs.

This is a working-capital model. It does not yet include payment fees, shipping,
taxes, storage, staffing, or delayed replenishment.

## Configuration

- `box_price`: customer price for one reveal.
- `simulations`: number of independent Monte Carlo runs.
- `openings_per_simulation`: operating horizon in each run.
- `confidence_level`: percentile used for recommended starting cash.
- `default_buyback_offer_rate`: instant-buyback offer as a share of purse price.
- `default_starting_inventory`: initial units purchased per purse.
- `seed`: makes results reproducible.

CLI flags such as `--box-price`, `--simulations`, `--openings`, `--confidence`,
and `--seed` override the JSON configuration.

## Run the tests

```powershell
python -m unittest discover -s tests
```
