<script setup lang="ts">
import { formatUTCTime } from '../../utils/time'
import type { TodayGame } from '../../types/leaderboard'
import { useTeamColors } from '../../composables/useTeamColors'

const props = defineProps<{
  games: TodayGame[]
}>()

const { getColors } = useTeamColors()

function statusLabel(game: TodayGame): string {
  if (game.status === 2) return game.status_text || 'LIVE'
  if (game.status === 3) return 'Final'
  if (game.game_time) {
    return formatUTCTime(game.game_time, { hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
  }
  return game.status_text || ''
}

function statusClass(game: TodayGame): string {
  if (game.status === 2) return 'bg-green-500/20 text-green-400 border border-green-500/30'
  if (game.status === 3) return 'bg-surface-700 text-surface-300'
  return 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
}

function isWinner(score: number | null, otherScore: number | null, status: number): boolean {
  return status === 3 && score !== null && otherScore !== null && score > otherScore
}

function todayRecord(wins: number | null, losses: number | null): string | null {
  if (wins === null || losses === null) return null
  return `${wins}-${losses}`
}

function fmtPct(p: number): string {
  return Math.round(p * 100) + '%'
}
</script>

<template>
  <div v-if="games.length === 0" class="p-6 text-center text-surface-400">
    <i class="pi pi-calendar text-3xl mb-2 block"></i>
    <p class="text-sm">No games today</p>
  </div>
  <div v-else class="flex flex-col divide-y divide-[var(--p-content-border-color)]">
    <div v-for="game in props.games" :key="game.game_id" class="px-4 py-3">

      <!-- Status badge + NBA.com link -->
      <div class="flex items-center justify-between mb-2">
        <span :class="['text-xs font-semibold px-2 py-0.5 rounded-full', statusClass(game)]">
          {{ statusLabel(game) }}
        </span>
        <a v-if="game.game_url" :href="game.game_url" target="_blank" rel="noopener noreferrer"
          class="text-xs text-surface-400 hover:text-surface-200 flex items-center gap-1 transition-colors flex-shrink-0">
          <img src="https://cdn.nba.com/logos/leagues/logo-nba.svg" alt="NBA.com" class="h-3.5" /><i class="pi pi-external-link text-[10px]"></i>
        </a>
      </div>

      <!-- Team rows + optional right-side gauge -->
      <div class="flex gap-3">

        <!-- Team rows -->
        <div class="flex-1 min-w-0">
          <!-- Away team -->
          <div class="flex items-center gap-3 mb-1">
            <img :src="game.away_team_logo_url || 'https://cdn.nba.com/logos/nba/fallback.svg'" :alt="game.away_team_tricode || 'TBD'"
              class="w-8 h-8 object-contain flex-shrink-0"
              :class="{ 'opacity-40': game.status === 3 && !isWinner(game.away_score, game.home_score, game.status), 'opacity-30': !game.away_team_logo_url }" />
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold truncate"
                :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.away_score, game.home_score, game.status) }">
                <span v-if="game.away_seed" class="text-xs font-normal text-surface-400 mr-1">{{ game.away_seed }}</span>{{ game.away_team_name || 'TBD' }}
              </p>
              <p v-if="game.away_owner" class="text-xs text-surface-400 truncate">
                {{ game.away_owner }}
                <template v-if="game.away_owner_wins !== null">
                  <span class="text-surface-400"> · {{ game.away_owner_wins }} Wins</span>
                  <span v-if="todayRecord(game.away_owner_today_wins, game.away_owner_today_losses)" class="text-surface-400"> · {{ todayRecord(game.away_owner_today_wins, game.away_owner_today_losses) }} Today</span>
                </template>
              </p>
            </div>
            <span v-if="game.status !== 1 && game.away_score !== null" class="text-lg font-bold tabular-nums flex-shrink-0"
              :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.away_score, game.home_score, game.status) }">
              {{ game.away_score }}
            </span>
          </div>

          <!-- Home team -->
          <div class="flex items-center gap-3">
            <img :src="game.home_team_logo_url || 'https://cdn.nba.com/logos/nba/fallback.svg'" :alt="game.home_team_tricode || 'TBD'"
              class="w-8 h-8 object-contain flex-shrink-0"
              :class="{ 'opacity-40': game.status === 3 && !isWinner(game.home_score, game.away_score, game.status), 'opacity-30': !game.home_team_logo_url }" />
            <div class="flex-1 min-w-0">
              <p class="text-sm font-semibold truncate"
                :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.home_score, game.away_score, game.status) }">
                <span v-if="game.home_seed" class="text-xs font-normal text-surface-400 mr-1">{{ game.home_seed }}</span>{{ game.home_team_name || 'TBD' }}
              </p>
              <p v-if="game.home_owner" class="text-xs text-surface-400 truncate">
                {{ game.home_owner }}
                <template v-if="game.home_owner_wins !== null">
                  <span class="text-surface-400"> · {{ game.home_owner_wins }} Wins</span>
                  <span v-if="todayRecord(game.home_owner_today_wins, game.home_owner_today_losses)" class="text-surface-400"> · {{ todayRecord(game.home_owner_today_wins, game.home_owner_today_losses) }} Today</span>
                </template>
              </p>
            </div>
            <span v-if="game.status !== 1 && game.home_score !== null" class="text-lg font-bold tabular-nums flex-shrink-0"
              :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.home_score, game.away_score, game.status) }">
              {{ game.home_score }}
            </span>
          </div>
        </div>

        <!-- Right-side vertical gauge (pregame + in-game) -->
        <div v-if="game.status !== 3 && game.away_win_pct !== null && game.home_win_pct !== null"
          class="flex items-stretch gap-1.5 flex-shrink-0">
          <div class="w-1.5 rounded-full overflow-hidden flex flex-col">
            <div class="w-full flex-shrink-0 transition-all duration-500" :style="{ height: fmtPct(game.away_win_pct), background: getColors(game.away_team_tricode, game.home_team_tricode).away }"></div>
            <div class="w-full flex-1" :style="{ background: getColors(game.away_team_tricode, game.home_team_tricode).home }"></div>
          </div>
          <div class="flex flex-col justify-between py-0.5">
            <span class="text-[10px] font-semibold tabular-nums leading-none text-white">{{ fmtPct(game.away_win_pct) }}</span>
            <span class="text-[10px] font-semibold tabular-nums leading-none text-white">{{ fmtPct(game.home_win_pct) }}</span>
          </div>
        </div>

      </div>

      <!-- Game label + series info -->
      <div v-if="game.game_label || game.series_game_text || game.series_status_text"
        class="flex items-center justify-between mt-1.5 gap-2">
        <p v-if="game.game_label || game.series_game_text" class="text-xs text-surface-400">
          <template v-if="game.game_label">{{ game.game_label }}</template><template v-if="game.game_label && game.series_game_text"> · </template><template v-if="game.series_game_text">{{ game.series_game_text }}<template v-if="game.if_necessary"> (<span class="hidden sm:inline">if necessary</span><span class="inline sm:hidden">if nec.</span>)</template></template>
        </p>
        <div v-else></div>
        <p v-if="game.series_status_text" class="text-xs text-surface-400 flex-shrink-0">{{ game.series_status_text }}</p>
      </div>

      <!-- Arena + broadcaster logos -->
      <div class="flex items-center justify-between mt-1">
        <p v-if="game.arena_name" class="text-xs text-surface-400">
          {{ game.arena_name }} · {{ game.arena_city }}, {{ game.arena_state }}
        </p>
        <div class="flex items-center gap-1 ml-auto">
          <img v-for="logo in game.national_broadcaster_logos" :key="logo" :src="logo" class="h-3.5" />
        </div>
      </div>

    </div>
  </div>
</template>
