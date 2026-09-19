<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'

const steps = [
  {
    number: '1',
    title: 'Create a pool',
    copy: 'Recruit participants and set any house rules.',
    icon: 'pi pi-users',
    link: '/docs/pools',
    linkLabel: 'What is a wins pool?',
  },
  {
    number: '2',
    title: 'Draft Teams',
    copy: 'Run a real-time auction to set each roster.',
    icon: 'pi pi-megaphone',
    link: '/docs/auction',
    linkLabel: 'How the auction works',
  },
  {
    number: '3',
    title: 'Track Wins',
    copy: 'Check in on standings and projections.',
    icon: 'pi pi-chart-line',
    link: '/pools',
    linkLabel: 'Create a pool',
    linkIcon: 'pi pi-plus',
  },
]
</script>

<template>
  <div class="min-h-screen bg-[var(--p-content-background)]">
    <main>
      <section class="stickerbomb-background pb-24 pt-14 text-center sm:py-20">
        <div class="mx-auto max-w-5xl px-5 sm:px-8">
          <div class="mx-auto max-w-3xl">
            <h1 class="hero-text-shadow text-4xl font-bold leading-tight sm:text-6xl">
              NBA Wins Pool
            </h1>
            <p class="hero-text-shadow mx-auto mt-5 max-w-xl text-base leading-7 text-zinc-200 sm:mt-6 sm:text-xl sm:leading-8">
              Auction teams once, then watch the wins add up all season.<br />
              No daily lineups.
            </p>
            <div class="mx-auto mt-7 flex max-w-md flex-col gap-3 sm:mt-8 sm:max-w-none sm:flex-row sm:justify-center">
              <RouterLink :to="{ name: 'pools' }" custom v-slot="{ navigate }">
                <Button class="w-full sm:w-auto" size="large" label="Create a pool" @click="navigate" />
              </RouterLink>
              <RouterLink :to="{ name: 'pools' }" custom v-slot="{ navigate }">
                <Button class="w-full sm:w-auto" size="large" label="Browse pools" outlined @click="navigate" />
              </RouterLink>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" class="pb-12 sm:pb-16">
        <div class="mx-auto max-w-5xl px-5 sm:px-8">
          <h2 class="text-center text-3xl font-bold md:text-left sm:text-4xl">How it works</h2>

          <ol class="mx-auto mt-7 grid max-w-md gap-7 text-left md:mt-8 md:max-w-none md:grid-cols-3 md:gap-3">
            <li
              v-for="step in steps"
              :key="step.number"
              class="md:rounded-lg md:border md:border-[var(--p-content-border-color)] md:p-6"
            >
              <div class="flex items-start gap-4">
                <span class="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-contrast">{{ step.number }}</span>
                <div class="min-w-0 flex-1">
                  <h3 class="text-lg font-semibold md:text-xl">{{ step.title }}</h3>
                  <p class="mt-1.5 leading-6 text-zinc-400 md:mt-2">{{ step.copy }}</p>
                  <RouterLink v-if="step.link" :to="step.link" class="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
                    {{ step.linkLabel }}
                    <i :class="[step.linkIcon || 'pi pi-arrow-right', 'text-xs']" aria-hidden="true"></i>
                  </RouterLink>
                </div>
                <i :class="[step.icon, 'mt-1 hidden text-lg text-primary md:block']" aria-hidden="true"></i>
              </div>
            </li>
          </ol>
          <RouterLink
            :to="{ name: 'docs-index' }"
            class="ml-auto mt-10 flex w-fit items-center gap-2 text-sm font-semibold text-primary hover:underline"
          >
            Learn More
            <i class="pi pi-arrow-right text-xs" aria-hidden="true"></i>
          </RouterLink>
        </div>
      </section>
    </main>
  </div>
</template>