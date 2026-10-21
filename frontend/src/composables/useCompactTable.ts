import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * Whether the table in `root` overflows and should go compact; stays compact until the full width fits again.
 * Bind it to `data-compact` and use the `compact:` variant in cells.
 */
export function useCompactTable(root: Ref<HTMLElement | null | undefined>) {
  const compact = ref(false)
  let wideWidth = 0
  let observer: ResizeObserver | undefined
  let observedTable: Element | null = null

  function check() {
    const el = root.value
    if (!el) return
    const table = el.querySelector('.p-datatable-table')
    if (table && table !== observedTable) {
      if (observedTable) observer?.unobserve(observedTable)
      observer?.observe(table)
      observedTable = table
    }
    const scroller = el.querySelector<HTMLElement>('.p-datatable-table-container') ?? el
    const available = scroller.clientWidth
    if (!compact.value && scroller.scrollWidth > available + 1) {
      wideWidth = scroller.scrollWidth
      compact.value = true
    } else if (compact.value && available >= wideWidth) {
      compact.value = false
    }
  }

  onMounted(() => {
    observer = new ResizeObserver(check)
    watch(
      root,
      (el, previous) => {
        if (previous) observer?.unobserve(previous)
        if (el) observer?.observe(el)
        check()
      },
      { immediate: true },
    )
  })

  onBeforeUnmount(() => observer?.disconnect())

  return compact
}
