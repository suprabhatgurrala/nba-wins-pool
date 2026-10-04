---
name: auction-strategy
path: /docs/auction-strategy
navigationTitle: Auction Strategy
title: Auction Strategy
description: How to read the valuation table and the basics of bidding well.
---

## The Valuation Table

During the auction, the valuation table lists every team with numbers drawn from sportsbook odds. The columns are:

- **Reg Wins**: The team's projected regular-season wins, from the sportsbook's win total.
- **Over %**: The chance, according to the odds, that the team goes over that win total.
- **Playoffs %**: The chance the team makes the playoffs.
- **Conf %**: The chance the team wins its conference.
- **Title %**: The chance the team wins the championship.
- **Total Wins**: The team's expected wins for the whole season, including the playoffs.
- **Value**: A suggested price in auction dollars.

### How accurate are these numbers?

Sportsbook lines are among the most accurate publicly available projections, and they already account for factors like player quality, injuries, and strength of schedule. Even so, each number is an average over many possible outcomes, so some teams will beat theirs and others will fall short.

## How Total Wins Is Calculated

A pool counts playoff wins as well as regular-season wins, so Reg Wins alone doesn't show how many wins a team will get. Total Wins adds an estimate of playoff wins:

> Total Wins = Reg Wins + (Playoffs % × 2.78) + (Conf % × 19.77)

The two multipliers come from a linear regression of playoff wins against those two probabilities. In rough terms, the playoffs term covers the wins from early rounds, and the conference term covers the wins from deep playoff runs.

## How Value Is Calculated

Value answers the question: if every team were priced fairly, what would each cost? It rests on the idea of a **replacement level**, the quality of the last team likely to be drafted.

1. **Count the drafted teams.** This is the number of participants times Teams per Participant.
2. **Find the replacement level.** Rank all teams by Total Wins. The replacement level is the Total Wins of the last team that gets drafted. A team at that level is worth only the minimum bid.
3. **Measure each team over replacement.** Subtract the replacement level from each team's Total Wins. A team that wins 8 more games than the replacement is worth 8.
4. **Split the money by share.** The whole pool of money (participants times Starting Budget) is divided in proportion to those numbers. A team's Value is its share of the total wins above replacement times the total money.
5. **Round, with a floor of $1.** Values are rounded to whole dollars, and no team is valued below $1, including teams at or below replacement level.

### A small example

Say there are 3 participants with $100 each, and 2 teams per participant. That is $300 in total and 6 drafted teams. The six best teams have these Total Wins:

| Team | Total Wins | Over replacement | Value |
| ---- | ---------- | ---------------- | ----- |
| A    | 58         | 18               | $120  |
| B    | 52         | 12               | $80   |
| C    | 48         | 8                | $53   |
| D    | 45         | 5                | $33   |
| E    | 42         | 2                | $13   |
| F    | 40         | 0                | $1    |

Team F is the replacement level, so it is worth the $1 minimum. The wins over replacement add up to 45, so team A's value is 18 / 45 × $300 = $120.

## Basic Strategy

- **Treat Value as the fair price.** Paying much less is a bargain, and paying much more means you've overpaid in wins per dollar.
- **Look past the averages.** Expected wins are an average, so real results can vary widely. Aim for teams you think will outperform their numbers, and be careful with teams that carry extra risk.
- **Know your group.** Think about which teams might go for more or less because of your group's favorite teams and players. Notice whether people are overspending early or saving too much, and adjust your bids to match.
- **Decide between favorites and depth.** Spending big on a favorite leaves less for the rest of your roster. Spreading your budget across several mid-tier teams is steadier, but it gives up the top end. Neither is necessarily right or wrong, and the better choice depends on how your group bids or which teams you feel could outperform their expectation.
- **Use nominations on purpose.** You pick which team goes up for bidding. Nominating a team you want gets bidders spending on it, while nominating one you don't want can pull money away from your rivals. Following a snake order keeps nominations fair.
- **Bid with care.** Sometimes it makes sense to bid on a team you don't want, to push a rival into spending more. Be careful, though: if nobody outbids you, you're stuck with that team at your price.
- **Watch the money, not only the teams.** Compare the total budget everyone has left with the Values of the teams still available. If people are spending below Value early on, prices will climb later, and the reverse is also true.
