<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    size?: number
    color?: string
  }>(),
  {
    size: 10,
    color: undefined,
  },
)
</script>

<template>
  <span
    class="live-dot"
    :style="{ '--dot-size': `${props.size}px`, color: props.color }"
    aria-hidden="true"
  />
</template>

<style scoped>
.live-dot {
  position: relative;
  width: var(--dot-size, 10px);
  height: var(--dot-size, 10px);
  border-radius: 50%;
  background: currentColor;
  opacity: 0.9;
}

.live-dot::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
  animation: pulse 1.2s ease-out infinite;
}

@keyframes pulse {
  0% {
    transform: scale(1);
    opacity: 0.5;
  }
  70% {
    transform: scale(2);
    opacity: 0.2;
  }
  100% {
    transform: scale(2.5);
    opacity: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .live-dot::after {
    animation: none;
  }
}
</style>
