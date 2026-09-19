<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Button from 'primevue/button'
</script>

<template>
  <section>
    <h2>Next steps</h2>
    <p>Create a pool for your participants, or browse the public pools already underway.</p>
    <div class="mt-5 flex flex-col gap-3 sm:flex-row">
      <RouterLink :to="{ name: 'pools' }" custom v-slot="{ navigate }">
        <Button class="w-full" label="Create a pool" @click="navigate" />
      </RouterLink>
      <RouterLink :to="{ name: 'pools' }" custom v-slot="{ navigate }">
        <Button class="w-full" label="Browse pools" outlined @click="navigate" />
      </RouterLink>
    </div>
  </section>
</template>