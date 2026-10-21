import { computed, inject, provide, reactive, type ComputedRef, type InjectionKey } from 'vue'

/** Labels that shorten together: every member shows the shortest label any member needs. */
export interface FitGroup {
  levels: Map<symbol, number>
  level: ComputedRef<number>
}

const teamNameGroupKey: InjectionKey<FitGroup> = Symbol('teamNameGroup')

function createFitGroup(): FitGroup {
  const levels = reactive(new Map<symbol, number>())
  return { levels, level: computed(() => Math.max(0, ...levels.values())) }
}

/** Abbreviates every `TeamName` in the calling component once any one doesn't fit. */
export function provideTeamNameGroup(): FitGroup {
  const group = createFitGroup()
  provide(teamNameGroupKey, group)
  return group
}

/** The team name group provided by an ancestor, if any. */
export function useTeamNameGroup(): FitGroup | undefined {
  return inject(teamNameGroupKey, undefined)
}
