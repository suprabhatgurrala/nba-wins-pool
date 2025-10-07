<script setup lang="ts">
import { RouterView } from 'vue-router'
import Toast from 'primevue/toast'
import ConfirmDialog from 'primevue/confirmdialog'
import { onMounted } from 'vue'

onMounted(() => {
  // Force dark mode by adding the class to the document element
  document.documentElement.classList.add('dark-mode-always')
})
</script>

<template>
  <link rel="shortcut icon" type="image/png" href="/static/favicon.png" />
  <Toast class="max-w-[90vw] sm:max-w-md" />
  <ConfirmDialog />
  <RouterView />
</template>
