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
- **Total**: The team's expected wins for the whole season, including the playoffs.
- **RS**: The team's projected regular-season wins, from the sportsbook's win total.
- **Over RS**: The probability that the team goes over its regular-season win total.
- **Playoffs**: The probability the team makes the playoffs.
- **Finals**: The probability the team wins its conference and makes the NBA Finals.
- **Title**: The probability the team wins the championship.

### How accurate are these numbers?

For the five seasons from 2021-22 to 2025-26, a team's actual wins were 9 wins away from its projection on average. For comparison, if we just projected an average number of wins for every team, that would be 13 wins away on average.

Sportsbook lines are likely the best estimates available, but there is a lot of variability in an NBA season.

## How Total Wins Is Calculated

A pool counts playoff wins too, so a team's regular-season win total alone doesn't show how many wins it will get. Total Wins adds an estimate of playoff wins:

> Total = RS + (Playoffs × 2.78) + (Finals × 19.77)

The two multipliers come from a linear regression of playoff wins against the Playoffs and Finals probabilities. The Playoffs term accounts for the first round, while the Finals term accounts for deeper playoff runs.

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

- The path to winning a pool is to have teams that either outperform or, at worst, meet their expectations. A team that falls significantly short can make it harder to win.
- Paying more than the suggested Value raises the wins a team needs to pay off, and paying less lowers it. Only go over Value for teams you're confident will outperform.
- Pay attention to the number of slots you have left. Later in the auction, having a slot for a team can be more valuable than the budget you have left.
- Think about which combination of teams gives you the highest combined Total for your budget.
- Don't wait too long to spend your money. Unspent budget does nothing for you, and you might run out of teams that are worth spending it on.
- Use nominations wisely. Nominating a team you don't want can get other bidders to spend budget and a slot on it. Nominating a team you do want early lets you bid on it while others are still holding back their budget.
