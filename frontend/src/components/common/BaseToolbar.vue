<script setup lang="ts">
import { computed } from 'vue'
import Toolbar from 'primevue/toolbar'
import Button from 'primevue/button'

type ToolbarButtonConfig = {
  id?: string
  icon: string
  ariaLabel?: string
  severity?: string
  variant?: string
  disabled?: boolean
  tooltip?: string
}

const props = withDefaults(
  defineProps<{
    title?: string
    leftButtons?: ToolbarButtonConfig[]
    rightButtons?: ToolbarButtonConfig[]
  }>(),
  {
    title: '🏀 NBA Wins Pool 🏆',
    leftButtons: () => [{ icon: 'pi pi-home', ariaLabel: 'Home' }],
    rightButtons: () => [],
  }
)

const emit = defineEmits<{
  (e: 'left-click', payload: { index: number; id?: string }): void
  (e: 'right-click', payload: { index: number; id?: string }): void
}>()

const leftToShow = computed(() => (props.leftButtons || []).slice(0, 3))
const rightToShow = computed(() => (props.rightButtons || []).slice(0, 3))

function onLeftClick(index: number) {
  const btn = leftToShow.value[index]
  emit('left-click', { index, id: btn?.id })
}

function onRightClick(index: number) {
  const btn = rightToShow.value[index]
  emit('right-click', { index, id: btn?.id })
}
</script>

<template>
  <Toolbar style="background-color: transparent; border: none; min-height: 4.5rem" v-bind="$attrs">
    <template #start>
      <div class="flex items-center gap-2">
        <Button
          v-for="(btn, idx) in leftToShow"
          :key="btn.id ?? idx"
          :icon="btn.icon"
          :aria-label="btn.ariaLabel || 'Toolbar button'"
          :severity="btn.severity || 'secondary'"
          :variant="btn.variant || 'outlined'"
          :disabled="btn.disabled ?? false"
          v-tooltip="btn.tooltip"
          @click="onLeftClick(idx)"
        />
      </div>
    </template>
    <template #center>
      <p class="text-xl font-bold">
        <slot name="title">{{ title }}</slot>
      </p>
    </template>
    <template #end>
      <div class="flex items-center gap-2">
        <Button
          v-for="(btn, idx) in rightToShow"
          :key="btn.id ?? idx"
          :icon="btn.icon"
          :aria-label="btn.ariaLabel || 'Toolbar button'"
          :severity="btn.severity || 'secondary'"
          :variant="btn.variant || 'outlined'"
          :disabled="btn.disabled ?? false"
          v-tooltip="btn.tooltip"
          @click="onRightClick(idx)"
        />
      </div>
    </template>
  </Toolbar>
</template>
