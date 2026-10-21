/**
 * Batches the fit checks of every `FitText` on the page. Each check needs to undo its own sizing, measure, then apply
 * the result; done one element at a time, every element after the first forces the browser to lay out the page again.
 * Here all the elements that need a check go through each step together, alternating writes and reads, so a batch
 * costs a few layouts however many elements are in it.
 *
 * Targets run in passes by `pass` (lowest first), each pass through every step, so a target can depend on the final
 * layout of earlier ones: table headers that collapse go first, then the names in the rows they make room for.
 *
 * One ResizeObserver watches every element any member depends on, and a batch runs inside its callback (before the
 * next paint) or, for checks scheduled from elsewhere, in a microtask.
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
