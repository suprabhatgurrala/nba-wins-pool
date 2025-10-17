<script setup lang="ts">
import { computed } from 'vue'
import Avatar from 'primevue/avatar'

const props = withDefaults(
  defineProps<{
    name?: string
    size?: 'small' | 'normal' | 'large' | 'xlarge'
    imageUrl?: string | null
    showLabel?: boolean
    icon?: string
    backgroundColor?: string
    customClass?: string
  }>(),
  {
    name: '',
    size: 'normal',
    imageUrl: null,
    showLabel: false,
    icon: undefined,
    backgroundColor: undefined,
    customClass: '',
  },
)

// Avatar color palette
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

// Get initials from name - matches AuctionOverview logic
function getInitials(name: string): string {
  if (!name) return '??'
  const segments = name.trim().split(/\s+/).filter(Boolean)
  if (!segments.length) return '??'
  const [first, second] = segments
  const initials = `${first?.[0] ?? ''}${second?.[0] ?? first?.[1] ?? ''}`
  return initials.toUpperCase().slice(0, 2)
}

// Get consistent color for name
function getAvatarColor(name: string): string {
  if (!name) return '#1f2937'
  const index = hashString(name) % avatarPalette.length
  return avatarPalette[index]
}

const initials = computed(() => getInitials(props.name))
const computedBackgroundColor = computed(() => props.backgroundColor || getAvatarColor(props.name))

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
    <!-- Image avatar -->
    <Avatar
      v-if="imageUrl"
      :image="imageUrl"
      shape="circle"
      :class="[sizeClass, 'font-medium', customClass]"
    />
    <!-- Icon avatar -->
    <Avatar
      v-else-if="icon"
      shape="circle"
      :class="[sizeClass, customClass]"
      :style="{ backgroundColor: computedBackgroundColor }"
    >
      <i :class="icon"></i>
    </Avatar>
    <!-- Initials avatar -->
    <Avatar
      v-else
      :label="initials"
      shape="circle"
      :class="[sizeClass, 'font-medium', customClass]"
      :style="{ backgroundColor: computedBackgroundColor }"
    />
    <span v-if="showLabel" class="text-sm font-medium">{{ name }}</span>
  </div>
</template>
