import { onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'

/**
 * Tracks whether the DataTable inside `root` should use its compact form: true when the full form overflows its
 * container, false again once there's room for the full form. The full form's width is remembered when it overflows,
 * so the table doesn't flip back and forth at the edge.
 *
 * Bind the result to `data-compact` on `root`: compact tables hide the sort icon on unsorted columns (see `main.css`),
 * and cells switch forms with the `compact:` variant (e.g. `compact:hidden` on two decimals, `hidden compact:inline` on
 * one), which is pure CSS so DataTable cell templates don't need to re-render.
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
