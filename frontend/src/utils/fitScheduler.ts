/**
 * Batches every FitText's fit check into shared read/write phases so a batch costs a few layouts, not one per label.
 * Lower `pass` targets run first, so headers settle before the names beneath them.
 */
export interface FitTarget {
  /** Which pass this target runs in; lower passes finish first. */
  pass: number
  /** Write: clear the sizes the last batch applied, and set up any measurement that needs special sizing. */
  prepare(): void
  /** Read: measurements taken under the special sizing. */
  measureSetup(): void
  /** Write: undo the special sizing. */
  reset(): void
  /** Read: measure the space and the labels, and decide which label to show. */
  measure(): void
  /** Write: apply sizes that follow from the decision. */
  apply(): void
  /** Read: measurements of the label as shown. */
  measureShown(): void
  /** Write: final sizes. */
  applyShown(): void
}

const PHASES: Exclude<keyof FitTarget, 'pass'>[] = [
  'prepare',
  'measureSetup',
  'reset',
  'measure',
  'apply',
  'measureShown',
  'applyShown',
]

const dirty = new Set<FitTarget>()
const watchers = new Map<Element, Set<FitTarget>>()
const watched = new Map<FitTarget, Element[]>()
let scheduled = false
let observer: ResizeObserver | undefined

function run() {
  scheduled = false
  if (!dirty.size) return
  const batch = [...dirty]
  dirty.clear()
  const passes = [...new Set(batch.map((t) => t.pass))].sort((a, b) => a - b)
  for (const pass of passes) {
    const targets = batch.filter((t) => t.pass === pass)
    for (const phase of PHASES) {
      for (const target of targets) target[phase]()
    }
  }
}

function getObserver(): ResizeObserver {
  observer ??= new ResizeObserver((entries) => {
    for (const entry of entries) {
      for (const target of watchers.get(entry.target) ?? []) dirty.add(target)
    }
    run()
  })
  return observer
}

/** Checks `target` in the next batch. */
export function scheduleFit(target: FitTarget) {
  dirty.add(target)
  if (scheduled) return
  scheduled = true
  queueMicrotask(run)
}

/** Re-checks `target` whenever any of `elements` resizes (replacing what it watched before). */
export function watchFit(target: FitTarget, elements: Element[]) {
  unwatchFit(target)
  const resizeObserver = getObserver()
  for (const element of elements) {
    let targets = watchers.get(element)
    if (!targets) {
      targets = new Set()
      watchers.set(element, targets)
      resizeObserver.observe(element)
    }
    targets.add(target)
  }
  watched.set(target, elements)
}

/** Stops watching for `target` and drops any pending check. */
export function unwatchFit(target: FitTarget) {
  dirty.delete(target)
  for (const element of watched.get(target) ?? []) {
    const targets = watchers.get(element)
    targets?.delete(target)
    if (targets && !targets.size) {
      watchers.delete(element)
      observer?.unobserve(element)
    }
  }
  watched.delete(target)
}
