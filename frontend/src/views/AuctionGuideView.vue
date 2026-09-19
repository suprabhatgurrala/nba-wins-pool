<script setup lang="ts">
import DocsLayout from '@/components/common/DocsLayout.vue'
import DocsActions from '@/components/docs/DocsActions.vue'
</script>

<template>
  <DocsLayout>
      <section>
        <h2>Set up the auction</h2>
        <p>
          Choose the number of teams per participant, a starting budget, and a minimum bid increment. Participants can be loaded from pool rosters, and each available team is added as an <strong>auction lot</strong>.
        </p>
        <p>
          An auction needs at least two participants and enough lots for everyone to fill their roster. Settings, participants, and lots can be changed while it is <strong>Not Started</strong>, then are locked once bidding begins.
        </p>
      </section>

      <section>
        <h2>Lot lifecycle</h2>
        <p>
          A lot is one team being offered in the auction. Everyone in the room sees bids and lot changes as they happen, and the activity feed records them.
        </p>
        <dl class="mt-5 grid gap-5">
          <div>
            <dt class="font-semibold">Ready</dt>
            <dd class="mt-1 leading-7 text-zinc-400">The lot is available to nominate. An opening bid moves it to Open.</dd>
          </div>
          <div>
            <dt class="font-semibold">Open</dt>
            <dd class="mt-1 leading-7 text-zinc-400">The lot accepts bids. Only one lot can be open at a time.</dd>
          </div>
          <div>
            <dt class="font-semibold">Closed</dt>
            <dd class="mt-1 leading-7 text-zinc-400">Anyone in the room can close the lot. Its high bidder wins the team at the final price, and the next lot can be nominated.</dd>
          </div>
        </dl>
      </section>

      <section>
        <h2>Bidding and budgets</h2>
        <p>
          Select the participant placing the bid, then enter an amount. Spectator mode is view-only. The opening bid and every later bid must meet the minimum increment.
        </p>
        <p>
          A leading bid uses the participant's budget; it is refunded when they are outbid. Participants cannot exceed their team limit, and the maximum bid reserves enough budget to make the minimum bid on remaining roster spots. The <strong>Min</strong> and <strong>Max</strong> controls show the valid range.
        </p>
      </section>

      <section>
        <h2>Valuations and projections</h2>
        <p>
          The valuation table helps compare lots. It can show projected regular-season wins, playoff and championship probabilities, expected total wins, and an estimated auction value.
        </p>
        <p>
          Values are guidance, not required prices. They reflect the auction's budget, participant count, and roster size; projections help with bidding but never affect standings or bid rules.
        </p>
      </section>

      <section>
        <h2>Completing the auction</h2>
        <p>
          Close any open lot, then complete the auction to make it read-only. Back on the pool page, load the results into rosters: every closed lot with a winning bid assigns its team and final price to that participant.
        </p>
      </section>

      <DocsActions />
  </DocsLayout>
</template>