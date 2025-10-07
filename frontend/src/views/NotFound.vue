<script setup lang="ts">
import Button from 'primevue/button'
import { useRouter } from 'vue-router'

const router = useRouter()

function goHome() {
  router.replace({ name: 'pools' })
}
</script>

<template>
  <main>
    <div class="not-found">
      <div class="code">404</div>
      <h1 class="title">Page Not Found</h1>
      <p class="detail">The page you are looking for does not seem to be here.</p>

      <div class="actions">
        <Button icon="pi pi-home" label="Home" @click="goHome"></Button>
      </div>
    </div>
  </main>
</template>

<style>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  text-align: center;
  padding: 2rem 1rem 3rem;
  margin: 0 auto;
  max-width: 720px;
}

.code {
  font-size: 4rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: var(--text-color-secondary);
}

.title {
  margin: 0.25rem 0 0.5rem;
}

.detail {
  color: var(--text-color-secondary);
  margin: 0;
}

.actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.75rem;
}

.primary {
  padding: 0.6rem 1rem;
  border-radius: 8px;
  background: var(--primary-color);
  color: white;
  border: none;
  cursor: pointer;
}
</style>
