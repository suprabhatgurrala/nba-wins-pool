---
name: auction-strategy
path: /docs/auction-strategy
navigationTitle: Auction Strategy
title: Auction Strategy
description: How to read the valuation table and the basics of bidding well.
---

## The Valuation Table

All probabilities below come from sportsbook odds, converted to implied probabilities and adjusted for the vig (the sportsbook's built-in margin).

- **Value**: A suggested price in auction dollars.
- **Total Wins**: The team's expected wins for the whole season, including the playoffs.
- **Regular Season Wins** (RS Wins): The team's projected regular-season wins, from the sportsbook's win total.
- **Over Win Total %** (Over %): The probability that the team goes over its regular-season win total.
- **Make Playoffs %** (PO %): The probability the team makes the playoffs.
- **Conference Winner %** (CW %): The probability the team wins its conference.
- **Finals Winner %** (FW %): The probability the team wins the championship.

### How accurate are these numbers?

For the five seasons from 2021-22 to 2025-26, a team's actual wins were 9 wins away from its projection on average. For comparison, if we just projected an average number of wins for every team, that would be 13 wins away on average.

Sportsbook lines are likely the best estimates available, but there is a lot of variability in an NBA season.

## How Total Wins Is Calculated

A pool counts playoff wins as well as regular-season wins, so Regular Season Wins alone doesn't show how many wins a team will get. Total Wins adds an estimate of playoff wins:

> Total Wins = Regular Season Wins + (Make Playoffs % × 2.78) + (Conference Winner % × 19.77)

The two multipliers come from a linear regression of playoff wins against those two probabilities. In rough terms, the playoffs term covers the wins from early rounds, and the conference term covers the wins from deep playoff runs.

## How Value Is Calculated

The Value column takes each team's Total Wins and computes a fair value for your pool's auction using a value over replacement calculation.

1. The number of teams drafted is the number of participants times Teams per Participant. The team ranked at this number in Total Wins is our replacement level team.
2. Subtract the replacement level team's Total Wins from every other team's Total Wins to get each team's wins over replacement.
3. Add up the wins over replacement of all the drafted teams. A team's auction value is its share of that total, multiplied by the total money available in the auction.
4. Each value is rounded to the nearest dollar, and any team with a value less than the minimum bid increment is set at the minimum bid increment.

### A small example

Say there are 2 participants with $100 each, and 2 teams per participant. That is $200 in total and 4 drafted teams. The five best teams have these Total Wins:

| Team | Total Wins | Over replacement | Value |
| ---- | ---------- | ---------------- | ----- |
| A    | 58         | 13               | $113  |
| B    | 52         | 7                | $61   |
| C    | 48         | 3                | $26   |
| D    | 45         | 0                | $1    |
| E    | 42         | -3               | $1    |

Team D is ranked 4th, so it is the replacement level and has 0 wins over replacement. Team E is below it, so its wins over replacement is negative. Only the 4 drafted teams count toward the total, so the wins over replacement add up to 13 + 7 + 3 + 0 = 23. Team A's value is 13 / 23 × $200 ≈ $113. Teams D and E come out at $0 or less, so both are set to the minimum bid increment, which is $1 here.

## Strategy Tips

- Treat Value as the fair price. Paying much less is a bargain, and paying much more means you've overpaid in wins per dollar.
- Expected wins are an average, so real results can vary widely. Aim for teams you think will outperform their numbers, and be careful with teams that carry extra risk.
- Think about which teams might go for more or less because of your group's favorite teams and players. Notice whether people are overspending early or saving too much, and adjust your bids to match.
- Spending big on a favorite leaves less for the rest of your roster. Spreading your budget across several mid-tier teams is steadier, but it gives up the top end. Neither is necessarily right or wrong, and the better choice depends on how your group bids or which teams you feel could outperform their expectation.
- You pick which team goes up for bidding. Nominating a team you want gets bidders spending on it, while nominating one you don't want can pull money away from your rivals. Following a snake order keeps nominations fair.
- Sometimes it makes sense to bid on a team you don't want, to push a rival into spending more. Be careful, though: if nobody outbids you, you're stuck with that team at your price.
- Compare the total budget everyone has left with the Values of the teams still available. If people are spending below Value early on, prices will climb later, and the reverse is also true.
