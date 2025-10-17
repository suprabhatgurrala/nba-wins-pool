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

// Expanded avatar color palette with vibrant, distinguishable colors
// Using Tailwind color scale (500-600 range for good contrast with white text)
const avatarPalette = [
  '#ef4444', // red-500
  '#dc2626', // red-600
  '#f97316', // orange-500
  '#ea580c', // orange-600
  '#f59e0b', // amber-500
  '#d97706', // amber-600
  '#eab308', // yellow-500
  '#ca8a04', // yellow-600
  '#84cc16', // lime-500
  '#65a30d', // lime-600
  '#22c55e', // green-500
  '#16a34a', // green-600
  '#10b981', // emerald-500
  '#059669', // emerald-600
  '#14b8a6', // teal-500
  '#0d9488', // teal-600
  '#06b6d4', // cyan-500
  '#0891b2', // cyan-600
  '#0ea5e9', // sky-500
  '#0284c7', // sky-600
  '#3b82f6', // blue-500
  '#2563eb', // blue-600
  '#6366f1', // indigo-500
  '#4f46e5', // indigo-600
  '#8b5cf6', // violet-500
  '#7c3aed', // violet-600
  '#a855f7', // purple-500
  '#9333ea', // purple-600
  '#d946ef', // fuchsia-500
  '#c026d3', // fuchsia-600
  '#ec4899', // pink-500
  '#db2777', // pink-600
  '#f43f5e', // rose-500
  '#e11d48', // rose-600
]

/**
 * DJB2 hash function - simple, fast, and good distribution
 * This is a well-known string hashing algorithm that provides
 * consistent results across sessions and good distribution.
 * 
 * @param str - String to hash
 * @returns Positive integer hash value
 */
function hashString(str: string): number {
  let hash = 5381 // DJB2 magic number
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i)
    // hash * 33 + char (using bitwise for performance)
    hash = ((hash << 5) + hash) + char
  }
  // Ensure positive number
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
