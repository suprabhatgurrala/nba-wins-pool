<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

const props = defineProps<{
  modelValue: string | null       // YYYY-MM-DD currently viewed date
  scoreboardDate: string | null   // YYYY-MM-DD "today" anchor
  gameDates: string[]             // all dates in season with games
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', date: string): void
}>()

const open = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)

// Position of the teleported dropdown
const dropdownStyle = ref({ top: '0px', right: '0px' })

function updatePosition() {
  if (!triggerRef.value) return
  const rect = triggerRef.value.getBoundingClientRect()
  const scrollY = window.scrollY
  dropdownStyle.value = {
    top: `${rect.bottom + scrollY + 8}px`,
    right: `${window.innerWidth - rect.right}px`,
  }
}

// Calendar month in view — starts at the month of the currently selected date
const viewYear = ref(0)
const viewMonth = ref(0) // 0-indexed

function initView() {
  const base = props.modelValue || props.scoreboardDate
  if (base) {
    const d = new Date(base + 'T12:00:00')
    viewYear.value = d.getFullYear()
    viewMonth.value = d.getMonth()
  }
}
watch(() => props.modelValue, initView)
onMounted(initView)

const MONTH_NAMES = ['January','February','March','April','May','June','July','August','September','October','November','December']
const DAY_LABELS = ['Su','Mo','Tu','We','Th','Fr','Sa']

const gameDateSet = computed(() => new Set(props.gameDates))
const seasonStart = computed(() => props.gameDates[0] ?? null)
const seasonEnd = computed(() => props.gameDates[props.gameDates.length - 1] ?? null)

const calendarDays = computed(() => {
  const year = viewYear.value
  const month = viewMonth.value
  const firstDay = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells: Array<{ date: string | null; day: number | null }> = []
  for (let i = 0; i < firstDay; i++) cells.push({ date: null, day: null })
  for (let d = 1; d <= daysInMonth; d++) {
    const mm = String(month + 1).padStart(2, '0')
    const dd = String(d).padStart(2, '0')
    cells.push({ date: `${year}-${mm}-${dd}`, day: d })
  }
  return cells
})

function isSelected(date: string | null) { return date !== null && date === props.modelValue }
function isToday(date: string | null) { return date !== null && date === props.scoreboardDate }
function hasGame(date: string | null) { return date !== null && gameDateSet.value.has(date) }
function isDisabled(date: string | null) {
  if (!date) return true
  if (seasonStart.value && date < seasonStart.value) return true
  if (seasonEnd.value && date > seasonEnd.value) return true
  return false
}

function canGoPrevMonth() {
  if (!seasonStart.value) return false
  const prev = new Date(viewYear.value, viewMonth.value - 1, 1)
  const start = new Date(seasonStart.value + 'T12:00:00')
  return prev.getFullYear() * 12 + prev.getMonth() >= start.getFullYear() * 12 + start.getMonth()
}
function canGoNextMonth() {
  if (!seasonEnd.value) return false
  const next = new Date(viewYear.value, viewMonth.value + 1, 1)
  const end = new Date(seasonEnd.value + 'T12:00:00')
  return next.getFullYear() * 12 + next.getMonth() <= end.getFullYear() * 12 + end.getMonth()
}

function prevMonth() {
  if (!canGoPrevMonth()) return
  if (viewMonth.value === 0) { viewMonth.value = 11; viewYear.value-- }
  else viewMonth.value--
}
function nextMonth() {
  if (!canGoNextMonth()) return
  if (viewMonth.value === 11) { viewMonth.value = 0; viewYear.value++ }
  else viewMonth.value++
}

function selectDate(date: string | null) {
  if (!date || isDisabled(date)) return
  emit('update:modelValue', date)
  open.value = false
}

function goToToday() {
  if (!props.scoreboardDate) return
  emit('update:modelValue', props.scoreboardDate)
  open.value = false
}

async function toggleOpen() {
  if (props.disabled) return
  if (!open.value) {
    initView()
    updatePosition()
    await nextTick()
    updatePosition() // recalc after DOM settles
  }
  open.value = !open.value
}

function onClickOutside(e: MouseEvent) {
  const target = e.target as Node
  if (
    open.value &&
    triggerRef.value && !triggerRef.value.contains(target) &&
    dropdownRef.value && !dropdownRef.value.contains(target)
  ) {
    open.value = false
  }
}

function onScroll() { if (open.value) updatePosition() }

onMounted(() => {
  document.addEventListener('mousedown', onClickOutside)
  window.addEventListener('scroll', onScroll, true)
})
onUnmounted(() => {
  document.removeEventListener('mousedown', onClickOutside)
  window.removeEventListener('scroll', onScroll, true)
})

const displayLabel = computed(() => {
  const d = props.modelValue || props.scoreboardDate
  if (!d) return 'Pick date'
  const dt = new Date(d + 'T12:00:00')
  return dt.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
})

const isOnToday = computed(() => props.modelValue === props.scoreboardDate)
</script>

<template>
  <div ref="triggerRef">
    <!-- Trigger -->
    <button
      @click="toggleOpen"
      :disabled="disabled"
      class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border transition-all duration-150 select-none disabled:opacity-40"
      :class="open
        ? 'bg-surface-700 border-surface-500 text-surface-100'
        : 'bg-surface-800 border-surface-700 text-surface-300 hover:border-surface-500 hover:text-surface-100'"
    >
      <i class="pi pi-calendar text-xs opacity-60 hidden sm:block"></i>
      <span class="text-xs font-medium tabular-nums">{{ displayLabel }}</span>
      <i class="pi pi-chevron-down text-[10px] opacity-50 transition-transform duration-150" :class="{ 'rotate-180': open }"></i>
    </button>

    <!-- Calendar dropdown — teleported to body to escape overflow:hidden ancestors -->
    <Teleport to="body">
      <Transition
        enter-active-class="transition duration-150 ease-out"
        enter-from-class="opacity-0 translate-y-1 scale-95"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition duration-100 ease-in"
        leave-from-class="opacity-100 translate-y-0 scale-100"
        leave-to-class="opacity-0 translate-y-1 scale-95"
      >
        <div
          v-if="open"
          ref="dropdownRef"
          class="fixed z-[9999] w-64 rounded-xl border border-surface-600 shadow-2xl shadow-black/60 overflow-hidden"
          :style="{ top: dropdownStyle.top, right: dropdownStyle.right, background: 'color-mix(in srgb, var(--p-surface-800) 80%, var(--p-surface-900) 20%)' }"
        >
          <!-- Month navigation -->
          <div class="flex items-center justify-between px-3 pt-3 pb-2">
            <button
              @click="prevMonth"
              :disabled="!canGoPrevMonth()"
              class="w-6 h-6 flex items-center justify-center rounded text-surface-400 hover:text-surface-100 hover:bg-surface-700 disabled:opacity-20 transition-colors"
            >
              <i class="pi pi-chevron-left text-[10px]"></i>
            </button>
            <span class="text-xs font-semibold tracking-wide text-surface-200 uppercase">
              {{ MONTH_NAMES[viewMonth] }} {{ viewYear }}
            </span>
            <button
              @click="nextMonth"
              :disabled="!canGoNextMonth()"
              class="w-6 h-6 flex items-center justify-center rounded text-surface-400 hover:text-surface-100 hover:bg-surface-700 disabled:opacity-20 transition-colors"
            >
              <i class="pi pi-chevron-right text-[10px]"></i>
            </button>
          </div>

          <!-- Day-of-week headers -->
          <div class="grid grid-cols-7 px-2 pb-1">
            <span
              v-for="label in DAY_LABELS"
              :key="label"
              class="text-center text-[10px] font-medium text-surface-500 py-0.5"
            >{{ label }}</span>
          </div>

          <!-- Date grid -->
          <div class="grid grid-cols-7 px-2 pb-2 gap-y-0.5">
            <div
              v-for="(cell, i) in calendarDays"
              :key="i"
              class="flex flex-col items-center justify-center"
            >
              <button
                v-if="cell.date"
                @click="selectDate(cell.date)"
                :disabled="isDisabled(cell.date)"
                class="relative w-7 h-7 flex items-center justify-center rounded-lg text-xs font-medium transition-all duration-100 disabled:opacity-25 disabled:cursor-not-allowed"
                :class="[
                  isSelected(cell.date)
                    ? 'bg-primary text-white shadow-sm'
                    : isToday(cell.date)
                      ? 'text-primary ring-1 ring-primary/60 hover:bg-primary/15'
                      : hasGame(cell.date)
                        ? 'text-surface-200 hover:bg-surface-700'
                        : 'text-surface-500 hover:bg-surface-700 hover:text-surface-300',
                ]"
              >
                {{ cell.day }}
                <span
                  v-if="hasGame(cell.date) && !isSelected(cell.date)"
                  class="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full"
                  :class="isToday(cell.date) ? 'bg-primary' : 'bg-surface-500'"
                ></span>
              </button>
              <div v-else class="w-7 h-7"></div>
            </div>
          </div>

          <!-- Footer: Today button -->
          <div v-if="!isOnToday" class="border-t border-surface-700 px-3 py-2">
            <button
              @click="goToToday"
              class="w-full text-xs font-medium text-primary hover:text-primary/80 transition-colors py-0.5"
            >
              Back to today
            </button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
