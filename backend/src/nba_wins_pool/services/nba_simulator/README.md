# Simulation

## Overview

This module simulates the remainder of the NBA season to estimate how many total wins each team will finish with, and how likely each pool roster is to win. It runs 50,000 simulated versions of the rest of the season, then counts outcomes across all of them to produce probabilities.

The simulation auto-detects the current phase of the season (Regular Season, Play-In, or Playoffs) and runs the appropriate logic for each.

---

## Regular Season

_Documentation coming soon._

---

## Play-In

The Play-In phase begins once the regular season has ended. At this point, every team's win total is finalized - the only remaining uncertainty is which teams from the 7–10 seeds will advance to the playoffs as the 7-seed and 8-seed in each conference.

### Structure

Each conference runs the same three-game play-in bracket:

- **Game A**: #7 seed hosts #8 seed. Winner locks up the **7-seed** in the playoffs.
- **Game B**: #9 seed hosts #10 seed. Loser is **eliminated**.
- **Game C**: Game A loser hosts Game B winner. Winner earns the **8-seed**. Loser is eliminated.

### How win probabilities are estimated

For each game, the simulator uses the best available data source:

1. **FanDuel moneyline odds** - if a sportsbook line exists for the game, that implied probability is used directly. This is the most accurate signal since it reflects real money.
2. **ESPN Playoff BPI** - ESPN's power rating for each team, converted to a win probability using a standard formula. Used when FanDuel odds aren't available.
3. **Win-ratio fallback** - if neither is available, the probability is estimated as each team's share of combined regular-season wins (e.g. a 50-win team vs. a 40-win team → 56% win probability for the better team).

### Games already played

If some play-in games have already been played, those results are locked in and not re-simulated. The simulator only simulates the games that haven't happened yet.

### After the Play-In

Once the 7- and 8-seeds are determined (or simulated), the full playoff bracket is known and the playoff simulation runs immediately after.

---

## Playoffs

In the playoffs phase, all regular-season and play-in results are finalized. The simulator only simulates the remaining playoff series.

### Structure

Each conference runs a standard 4-round bracket:

- **Round 1**: 1v8, 4v5, 2v7, 3v6
- **Round 2**: Winners from R1 face each other (bracket-style - no reseeding)
- **Conference Finals**: Two remaining teams per conference
- **NBA Finals**: East champion vs. West champion

All series are best-of-7. Home court advantage goes to the higher seed for Games 1, 2, 5, and 7; the lower seed hosts Games 3, 4, and 6.

### How win probabilities are estimated

For each game in a series, the simulator uses:

1. **FanDuel moneyline odds** - the sportsbook line for the *next* scheduled game in the series, if available. Only applies to that specific game; future games in the same series fall back to power ratings.
2. **Calibrated power ratings** - a per-team strength number (derived from ESPN's Playoff BPI, then tuned to match FanDuel futures odds). The difference between two teams' ratings is fed into a formula to compute win probability, with a home-court adjustment of +2.5 rating points for the home team.
3. **Win-ratio fallback** - same as the play-in fallback, with a small home-court boost.

### Calibration

Before running the playoff simulation, the model calibrates each team's power rating to match FanDuel's implied championship and conference-win probabilities. This step uses an optimizer that iteratively adjusts ratings until the simulation's predicted outcomes align with the market.

The optimizer starts from the most recent previously-stored ratings when available (warm start), which makes it faster to converge.

### Series already in progress

If a playoff series has already started, the known game results are locked in and only the remaining games are simulated. Completed series are returned directly without any sampling.

### Pool outcomes

After the playoff bracket is simulated across all 50,000 runs, the simulator combines each team's regular-season wins with their simulated playoff wins. Each pool roster's total wins are summed across all their drafted teams, and win probabilities are computed by counting how often each roster finishes with the most wins across all simulations.
