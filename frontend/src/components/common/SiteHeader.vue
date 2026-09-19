<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <header>
    <slot name="top" />
    <div class="grid h-[74px] grid-cols-[2.5rem_1fr_2.5rem] items-center px-4">
      <div class="flex justify-start">
        <slot name="left" />
      </div>
      <div class="justify-self-center text-center text-xl font-bold">
        <slot name="center">
          <RouterLink :to="{ name: 'home' }">🏀 NBA Wins Pool 🏆</RouterLink>
        </slot>
      </div>
      <div class="flex justify-end">
        <slot name="right" />
      </div>
    </div>
  </header>
</template>