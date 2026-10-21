<script setup lang="ts">
/**
 * Shows `full` when it fits, otherwise `short`. Always requests the full label's width so it can grow back.
 * `lines`/`wrapFull` allow wrapping, `group` shortens with its group, `collapse` sizes to the shown label (headers).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { FitGroup } from '@/composables/useFitGroup'
import { scheduleFit, unwatchFit, watchFit, type FitTarget } from '@/utils/fitScheduler'

const props = defineProps<{
  full: string
  short?: string | null
  /** Tooltip; defaults to the full label while a shorter one is showing. */
  title?: string
  /** How many lines the short label may wrap onto; defaults to 1. */
  lines?: number
  /** Let the full label wrap onto `lines` lines as well, before switching to the short one. */
  wrapFull?: boolean
  /** Size to the label that's showing (for table headers). */
  collapse?: boolean
  /** Shorten together with the other members of this group. */
  group?: FitGroup
}>()

const wraps = computed(() => (props.lines ?? 1) > 1)

/** Whether the label at index `i` may wrap: the short one always (with `lines`), the full one with `wrapFull`. */
function wrapsAt(i: number): boolean {
  return wraps.value && (i === labels.value.length - 1 || (i === 0 && !!props.wrapFull))
}

const labels = computed(() =>
  props.short && props.short !== props.full ? [props.full, props.short] : [props.full],
)

const root = ref<HTMLElement>()
const natural = ref(0)
const id = Symbol('fitText')
const shown = computed(() =>
  props.group
    ? Math.min(Math.max(natural.value, props.group.level.value), labels.value.length - 1)
    : natural.value,
)

function labelEls(): HTMLElement[] {
  return root.value
    ? [...root.value.children].filter((c): c is HTMLElement => c instanceof HTMLElement)
    : []
}

function lastLabel(): HTMLElement | undefined {
  const els = labelEls()
  return els[els.length - 1]
}

function lineRects(label: HTMLElement): DOMRect[] {
  const range = document.createRange()
  range.selectNodeContents(label)
  return [...range.getClientRects()].filter((r) => r.width > 0)
}

function lineCount(label: HTMLElement): number {
  return new Set(lineRects(label).map((r) => Math.round(r.top))).size
}

/** The width of a wrapped label's longest line, which CSS can't shrink the label to on its own. */
function widestLine(label: HTMLElement): number {
  const lines = new Map<number, { left: number; right: number }>()
  for (const rect of lineRects(label)) {
    const top = Math.round(rect.top)
    const line = lines.get(top)
    lines.set(top, {
      left: Math.min(line?.left ?? rect.left, rect.left),
      right: Math.max(line?.right ?? rect.right, rect.right),
    })
  }
  return Math.max(...[...lines.values()].map((l) => l.right - l.left))
}

/** The fit check, split into scheduler phases so all FitTexts are measured in one batch. */
let floor = 0
let hugWidth = 0
const target: FitTarget = {
  get pass() {
    return props.collapse ? 0 : 1
  },
  prepare() {
    const els = labelEls()
    for (const label of els) {
      label.style.width = ''
      label.style.height = ''
    }
    const last = els[els.length - 1]
    if (wraps.value && last) last.style.width = 'min-content'
  },
  measureSetup() {
    const last = lastLabel()
    if (!wraps.value || !last) return
    floor = last.getBoundingClientRect().width
    if (lineCount(last) <= (props.lines ?? 1)) return
    last.style.width = 'max-content'
    last.style.whiteSpace = 'nowrap'
    floor = last.getBoundingClientRect().width
    last.style.whiteSpace = ''
  },
  reset() {
    const last = lastLabel()
    if (wraps.value && last) last.style.width = ''
  },
  measure() {
    const el = root.value
    const els = labelEls()
    const last = els[els.length - 1]
    if (!wraps.value) floor = last ? last.getBoundingClientRect().width : 0
    if (!el || els.length < 2) {
      natural.value = 0
    } else {
      const available = el.getBoundingClientRect().width + 0.5
      natural.value = els.findIndex(
        (label, i) =>
          i === els.length - 1 ||
          (wrapsAt(i)
            ? label.scrollWidth <= label.clientWidth + 0.5 && lineCount(label) <= (props.lines ?? 1)
            : label.getBoundingClientRect().width <= available),
      )
    }
    props.group?.levels.set(id, natural.value)
  },
  apply() {
    if (!root.value) return
    root.value.style.minWidth = floor ? `${Math.ceil(floor)}px` : ''
    for (const label of labelEls().slice(0, shown.value)) {
      if (props.collapse) label.style.width = '0'
      if (props.collapse || props.wrapFull) label.style.height = '0'
    }
  },
  measureShown() {
    const els = labelEls()
    const last = els[els.length - 1]
    hugWidth =
      wraps.value && last && shown.value === els.length - 1 && lineCount(last) > 1
        ? widestLine(last)
        : 0
  },
  applyShown() {
    const last = lastLabel()
    if (hugWidth && last) last.style.width = `${Math.ceil(hugWidth)}px`
  },
}

function watchElements() {
  if (!root.value) return
  const space = props.collapse ? root.value.closest('table')?.parentElement : undefined
  watchFit(target, [root.value, ...labelEls(), ...(space ? [space] : [])])
  scheduleFit(target)
}

onMounted(watchElements)

onBeforeUnmount(() => {
  unwatchFit(target)
  props.group?.levels.delete(id)
})

watch(
  () => props.group,
  (_, previous) => previous?.levels.delete(id),
)

watch(
  () => [...labels.value, props.collapse, props.lines, props.wrapFull],
  () => nextTick(watchElements),
)
</script>

<template>
  <span
    ref="root"
    class="grid min-w-0 grid-cols-[minmax(0,max-content)] overflow-hidden"
    :class="wraps ? 'items-start' : 'whitespace-nowrap'"
    :title="title ?? (shown > 0 ? full : undefined)"
  >
    <span
      v-for="(label, i) in labels"
      :key="i"
      class="col-start-1 row-start-1"
      :class="[
        wrapsAt(i) ? 'whitespace-normal text-balance' : 'w-max whitespace-nowrap',
        { invisible: i !== shown },
      ]"
      ><template v-if="wrapsAt(i)"
        ><template v-for="(word, w) in label.split(' ')" :key="w"
          >{{ w > 0 ? ' ' : '' }}<span class="whitespace-nowrap">{{ word }}</span></template
        ></template
      ><template v-else>{{ label }}</template></span
    >
  </span>
</template>
