<script setup lang="ts">
/**
 * A centered page column that stays at `max` unless its content is squeezed, in which case it widens just enough to
 * fit, up to the full width of its parent. With `fullOnTouch` it always takes the full width on touch screens
 * (tablets, phones), for pages whose content uses every bit of a small screen; `max` still applies on desktops.
 *
 * Squeezed means a sideways-scrolling region inside it (anything marked `data-scroll-x`, e.g. a wide table) can't show
 * all of its content. Pages whose content fits keep their margins, so rows don't get stretched apart; a table that
 * needs more room gets the space the margins were wasting. The fit is re-checked when the parent resizes or the content
 * changes (data loads, tab switches).
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps<{
  /** The preferred maximum width, as a CSS length (e.g. `64rem`). */
  max: string
  /** Take the full width on touch screens instead of stopping at `max`. */
  fullOnTouch?: boolean
}>()

const root = ref<HTMLElement>()
const MAX_PASSES = 4
const touchQuery = window.matchMedia('(pointer: coarse)')
const touch = ref(touchQuery.matches)
const baseMax = computed(() => (props.fullOnTouch && touch.value ? 'none' : props.max))
const onTouchChange = () => {
  touch.value = touchQuery.matches
  scheduleFit()
}

let resizeObserver: ResizeObserver | undefined
let mutationObserver: MutationObserver | undefined
let frame = 0

function scrollers(el: HTMLElement): HTMLElement[] {
  const found: HTMLElement[] = []
  for (const marked of el.querySelectorAll<HTMLElement>('[data-scroll-x]')) {
    const candidates = [
      marked,
      ...marked.querySelectorAll<HTMLElement>(':scope > *, :scope > * > *'),
    ]
    for (const candidate of candidates) {
      const overflow = getComputedStyle(candidate).overflowX
      if (overflow === 'auto' || overflow === 'scroll') found.push(candidate)
    }
  }
  return found
}

/**
 * Starts from `max` and widens in a few passes: each pass asks every scroller for its missing width and grows the
 * column by that much, scaled by how much of the column the scroller occupies. Passes repeat because content can
 * change shape as it widens (e.g. table headers switching to their long labels).
 */
function fit() {
  const el = root.value
  const available = el?.parentElement?.clientWidth
  if (!el || !available) return
  el.style.maxWidth = baseMax.value
  for (let pass = 0; pass < MAX_PASSES; pass++) {
    const width = el.clientWidth
    if (width >= available) return
    let target = width
    for (const scroller of scrollers(el)) {
      const missing = scroller.scrollWidth - scroller.clientWidth
      if (missing <= 1 || scroller.clientWidth === 0) continue
      const share = scroller.clientWidth / width
      target = Math.max(target, width + missing / share)
    }
    if (target <= width + 1) return
    el.style.maxWidth = `${Math.ceil(Math.min(target, available))}px`
  }
}

function scheduleFit() {
  cancelAnimationFrame(frame)
  frame = requestAnimationFrame(fit)
}

onMounted(() => {
  resizeObserver = new ResizeObserver(scheduleFit)
  if (root.value?.parentElement) resizeObserver.observe(root.value.parentElement)
  mutationObserver = new MutationObserver(scheduleFit)
  if (root.value) mutationObserver.observe(root.value, { childList: true, subtree: true })
  touchQuery.addEventListener('change', onTouchChange)
  scheduleFit()
})

onBeforeUnmount(() => {
  touchQuery.removeEventListener('change', onTouchChange)
  cancelAnimationFrame(frame)
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
})
</script>

<template>
  <div ref="root" class="mx-auto w-full" :style="{ maxWidth: baseMax }">
    <slot />
  </div>
</template>
