---
name: simulation
path: /docs/simulation
navigationTitle: Simulation
title: How the Simulation Works
description: How the season simulator estimates final wins and each roster's chance of winning the pool.
---

## Overview {#overview}

The simulator plays out the rest of the NBA season 100,000 times. Each run produces a final win total for every team, and therefore for every pool roster. Counting the outcomes across all of the runs gives each team's expected wins and each roster's chance of winning the pool.

## The Projections Table {#columns}

- **Record**: Wins and losses so far.
- **Preseason**: The projected total wins from when your auction took place. Each roster's number is the sum of its teams. It never changes, so it shows what everyone was expecting at the start.
- **Simulated Avg**: The average final win total across all of the simulated seasons. It accounts for the games each team has left, so it keeps updating all season.
- **Win Probability**: The share of simulated seasons where the roster finishes with the most wins.

Comparing Preseason to Simulated Avg shows who has gained or lost ground since the draft.

## Why simulate?

Early in the season, expected wins are easy to calculate directly. Sportsbooks publish win totals for every team, so no simulation is needed.

As the playoffs approach, an average is less useful. Playoff results are lumpy: a team that is knocked out in the first round and a team that reaches the Finals can end up with very different win totals, and the average of the two describes neither. A simulation keeps those separate outcomes visible, so it can show how likely each roster is to finish on top.

## How accurate is it?

The simulation is calibrated to Vegas futures odds, so its championship and conference-winner probabilities match what the sportsbooks expect. That makes it a good estimate of each roster's chances, though it is still a probability.
