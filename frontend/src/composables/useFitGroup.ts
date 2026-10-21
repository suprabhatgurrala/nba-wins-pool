import { computed, inject, provide, reactive, type ComputedRef, type InjectionKey } from 'vue'

/**
 * Labels that shorten together: each `FitText` in the group reports which label it would show on its own, and every
 * member shows the shortest of those, so a list or table column never mixes full names with abbreviations.
 */
export interface FitGroup {
  levels: Map<symbol, number>
  level: ComputedRef<number>
}

const teamNameGroupKey: InjectionKey<FitGroup> = Symbol('teamNameGroup')

function createFitGroup(): FitGroup {
  const levels = reactive(new Map<symbol, number>())
  return { levels, level: computed(() => Math.max(0, ...levels.values())) }
}

/**
 * Makes every `TeamName` rendered inside the calling component switch to its abbreviation as soon as any one of them
 * doesn't fit. Call it in the setup of the component that owns the list or table.
 */
export function provideTeamNameGroup(): FitGroup {
  const group = createFitGroup()
  provide(teamNameGroupKey, group)
  return group
}

/** The team name group provided by an ancestor, if any. */
export function useTeamNameGroup(): FitGroup | undefined {
  return inject(teamNameGroupKey, undefined)
}
