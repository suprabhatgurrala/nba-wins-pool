<script setup lang="ts">
import type { TodayGame } from '../../types/leaderboard'

const props = defineProps<{
  games: TodayGame[]
}>()

function statusLabel(game: TodayGame): string {
  if (game.status === 2) return game.status_text || 'LIVE'
  if (game.status === 3) return 'Final'
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
</script>

<template>
  <div v-if="games.length === 0" class="p-6 text-center text-surface-400">
    <i class="pi pi-calendar text-3xl mb-2 block"></i>
    <p class="text-sm">No games today</p>
  </div>
  <div v-else class="flex flex-col divide-y divide-[var(--p-content-border-color)]">
    <div v-for="game in props.games" :key="game.game_id" class="px-4 py-3">
      <!-- Status badge + link -->
      <div class="flex items-center justify-between mb-2">
        <span :class="['text-xs font-semibold px-2 py-0.5 rounded-full', statusClass(game)]">
          {{ statusLabel(game) }}
        </span>
        <a v-if="game.game_url" :href="game.game_url" target="_blank" rel="noopener noreferrer"
          class="text-xs text-surface-400 hover:text-surface-200 flex items-center gap-1 transition-colors">
          NBA.com <i class="pi pi-external-link text-[10px]"></i>
        </a>
      </div>

      <!-- Away team -->
      <div class="flex items-center gap-3 mb-1">
        <img v-if="game.away_team_logo_url" :src="game.away_team_logo_url" :alt="game.away_team_tricode"
          class="w-8 h-8 object-contain flex-shrink-0" />
        <div v-else class="w-8 h-8 flex-shrink-0 flex items-center justify-center text-xs font-bold text-surface-400">
          {{ game.away_team_tricode }}
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold truncate"
            :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.away_score, game.home_score, game.status) }">
            {{ game.away_team_name }}
          </p>
          <p v-if="game.away_owner" class="text-xs text-surface-400 truncate">{{ game.away_owner }}</p>
        </div>
        <span v-if="game.status !== 1 && game.away_score !== null" class="text-lg font-bold tabular-nums flex-shrink-0"
          :class="{
            'text-surface-400': game.status === 3 && !isWinner(game.away_score, game.home_score, game.status),
          }">
          {{ game.away_score }}
        </span>
      </div>

      <!-- Home team -->
      <div class="flex items-center gap-3">
        <img v-if="game.home_team_logo_url" :src="game.home_team_logo_url" :alt="game.home_team_tricode"
          class="w-8 h-8 object-contain flex-shrink-0" />
        <div v-else class="w-8 h-8 flex-shrink-0 flex items-center justify-center text-xs font-bold text-surface-400">
          {{ game.home_team_tricode }}
        </div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-semibold truncate"
            :class="{ 'text-surface-400': game.status === 3 && !isWinner(game.home_score, game.away_score, game.status) }">
            {{ game.home_team_name }}
          </p>
          <p v-if="game.home_owner" class="text-xs text-surface-400 truncate">{{ game.home_owner }}</p>
        </div>
        <span v-if="game.status !== 1 && game.home_score !== null" class="text-lg font-bold tabular-nums flex-shrink-0"
          :class="{
            'text-surface-400': game.status === 3 && !isWinner(game.home_score, game.away_score, game.status),
          }">
          {{ game.home_score }}
        </span>
      </div>
    </div>
  </div>
</template>
