<script setup lang="ts">
import { RouterLink } from 'vue-router'
import DocsLayout from '@/components/common/DocsLayout.vue'
import DocsActions from '@/components/docs/DocsActions.vue'
</script>

<template>
  <DocsLayout>
        <section>
          <h2>Overview</h2>
          <p class="mt-3 leading-7 text-zinc-300">
            A <strong>pool</strong> is the group taking part in the competition. Each participant gets a few teams, usually through an auction before the season.
          </p>
          <p class="mt-3 leading-7 text-zinc-300">
            Your teams make up your <strong>roster</strong>. When one of them wins a game, that win is added to your score. The standings rank participants by the combined wins of every team on their roster.
          </p>
        </section>

        <section>
          <h2>Scoring</h2>
          <p>
            A regular-season win, a play-in win, and a playoff win all count the same. The final score does not matter, and there are no player stats or complicated scoring categories to manage.
          </p>
          <p>
            A pool can continue across multiple years. Each <strong>season</strong> has its own rosters, standings, and optional house rules or prizes.
          </p>
        </section>

        <section id="following" class="scroll-mt-6">
          <h2>Standings and season updates</h2>
          <p>
            Once everyone has teams, the pool page follows game results and updates the standings as wins come in. No daily changes are required from participants.
          </p>
          <p>
            You can check which owned teams are playing today or look at the <strong>wins race</strong>, a chart of how each participant's total has changed over time. When current-season projections are available, they offer an estimate of where everyone may finish; they never change the actual score.
          </p>
        </section>

        <section>
          <h2>Assigning teams</h2>
          <p>
            Most groups use the built-in auction. Everyone starts with the same budget and bids on the teams they want. The winning teams are then added to each participant's roster.
          </p>
          <p>
            A pool organizer can also enter rosters manually, so the site still works if your group runs its draft somewhere else.
          </p>
          <RouterLink :to="{ name: 'auction-guide' }" class="mt-4 inline-flex items-center gap-2 font-semibold text-primary hover:underline">
            Learn about the auction draft <i class="pi pi-arrow-right text-sm" aria-hidden="true"></i>
          </RouterLink>
        </section>
      <DocsActions />
  </DocsLayout>
</template>