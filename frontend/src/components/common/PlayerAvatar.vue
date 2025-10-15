<script setup lang="ts">
import { computed } from 'vue'
import Avatar from 'primevue/avatar'

const props = withDefaults(
  defineProps<{
    name: string
    size?: 'small' | 'normal' | 'large' | 'xlarge'
    shape?: 'circle' | 'square'
    imageUrl?: string | null
    showLabel?: boolean
  }>(),
  {
    size: 'normal',
    shape: 'circle',
    imageUrl: null,
    showLabel: false,
  },
)

// Avatar color palette - consistent colors for participants
const avatarPalette = [
  '#ef4444', // red
  '#f97316', // orange
  '#f59e0b', // amber
  '#eab308', // yellow
  '#84cc16', // lime
  '#22c55e', // green
  '#10b981', // emerald
  '#14b8a6', // teal
  '#06b6d4', // cyan
  '#0ea5e9', // sky
  '#3b82f6', // blue
  '#6366f1', // indigo
  '#8b5cf6', // violet
  '#a855f7', // purple
  '#d946ef', // fuchsia
  '#ec4899', // pink
  '#f43f5e', // rose
]

// Hash function for consistent color assignment
function hashString(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    hash = (hash << 5) - hash + char
    hash = hash & hash // Convert to 32bit integer
  }
  return Math.abs(hash)
}

// Get initials from name
function getInitials(name: string): string {
  if (!name) return '??'
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  const initials = parts.map((p) => p[0]).join('')
  return initials.toUpperCase().slice(0, 2)
}

// Get consistent color for name
function getAvatarColor(name: string): string {
  if (!name) return '#1f2937'
  const index = hashString(name) % avatarPalette.length
  return avatarPalette[index]
}

const initials = computed(() => getInitials(props.name))
const backgroundColor = computed(() => getAvatarColor(props.name))

const sizeClass = computed(() => {
  switch (props.size) {
    case 'small':
      return 'size-6 text-xs'
    case 'normal':
      return 'size-8 text-sm'
    case 'large':
      return 'size-10 text-base'
    case 'xlarge':
      return 'size-12 text-lg'
    default:
      return 'size-8 text-sm'
  }
})
</script>

<template>
  <div class="flex items-center gap-2">
    <Avatar v-if="imageUrl" :image="imageUrl" :shape="shape" :class="[sizeClass, 'font-bold']" />
    <Avatar
      v-else
      :label="initials"
      :shape="shape"
      :class="[sizeClass, 'font-bold']"
      :style="{ backgroundColor }"
    />
    <span v-if="showLabel" class="text-sm font-medium">{{ name }}</span>
  </div>
</template>
