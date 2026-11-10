<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMediaQuery, usePreferredReducedMotion } from '@vueuse/core'
import { use } from 'echarts/core'
import type { EChartsOption, SeriesOption } from 'echarts'
import Button from 'primevue/button'
import VChart from 'vue-echarts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import { LineChart } from 'echarts/charts'
import { SVGRenderer } from 'echarts/renderers'
import type { WinsRaceMilestone } from '@/types/pool'

use([
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  LineChart,
  MarkLineComponent,
  SVGRenderer,
  ToolboxComponent,
  TooltipComponent,
])

export type TimelineRange = '1D' | '1W' | '1M' | 'ALL'
export interface TimelineLine {
  name: string
  points: [number, number | null][]
}

const DAY_MS = 24 * 60 * 60 * 1000
/** Okabe-Ito reordered, then Tol light cyan, Carbon Blue 50 and Tol light pink (frontend/research/colorblind-chart-palette.md). */
const LINE_COLORS = [
  '#56B4E9',
  '#F0E442',
  '#D55E00',
  '#0072B2',
  '#CC79A7',
  '#009E73',
  '#E69F00',
  '#99DDFF',
  '#4589ff',
  '#FFAABB',
]
const RANGE_SPANS: Record<TimelineRange, number | null> = {
  '1D': DAY_MS,
  '1W': 7 * DAY_MS,
  '1M': 30 * DAY_MS,
  ALL: null,
}
const PHONE_DEFAULT_RANGE: TimelineRange = '1M'

const props = withDefaults(
  defineProps<{
    /** One line per participant, in legend order; colors follow alphabetical order so they match across charts. */
    lines: TimelineLine[]
    milestones: WinsRaceMilestone[]
    ranges: TimelineRange[]
    formatValue: (value: number) => string
    formatAxisValue?: (value: number) => string
    /** Show the hour in the tooltip, for data finer than one point per day. */
    hourly?: boolean
    /** Start the y-axis at this value instead of fitting it to the data. */
    yMin?: number
    /** Round the top of the y-axis up to a multiple of this. */
    yStep?: number
  }>(),
  { hourly: false, yMin: undefined, yStep: undefined, formatAxisValue: undefined },
)

const reducedMotion = usePreferredReducedMotion()
const isPhone = useMediaQuery('(max-width: 650px)')

const initialRange: TimelineRange =
  isPhone.value && props.ranges.includes(PHONE_DEFAULT_RANGE) ? PHONE_DEFAULT_RANGE : 'ALL'
const range = ref<TimelineRange | null>(initialRange)
const chart = ref<InstanceType<typeof VChart>>()
let zoomWindow: { start: number; end: number } | null = null
let applyingRange = false
const zoomPercent = ref<{ start: number; end: number } | null>(null)
const SLIDER_INSET = 40
const TRACK_MARKER = 'rgba(1,1,1,0.004)'
const HANDLE_INSET = 1
const MIN_TAB_WIDTH = 40
const chartBox = ref<HTMLElement>()
const track = ref<{ left: number; width: number } | null>(null)

function measureTrack() {
  const box = chartBox.value
  const el = box?.querySelector<SVGElement>(
    `path[fill="${TRACK_MARKER}"], path[fill-opacity="0.004"]`,
  )
  if (!box || !el) return
  const r = el.getBoundingClientRect()
  const left = r.left - box.getBoundingClientRect().left
  const width = r.width
  if (track.value?.left !== left || track.value?.width !== width) track.value = { left, width }
}

const extent = computed(() => {
  let min = Infinity
  let max = -Infinity
  for (const line of props.lines) {
    for (const [t] of line.points) {
      if (t < min) min = t
      if (t > max) max = t
    }
  }
  return Number.isFinite(min) ? { min, max } : null
})

function rangeWindow(r: TimelineRange) {
  if (!extent.value) return null
  const span = RANGE_SPANS[r]
  const start =
    span === null ? extent.value.min : Math.max(extent.value.min, extent.value.max - span)
  return { start, end: extent.value.max }
}

function selectRange(r: TimelineRange) {
  range.value = r
  zoomWindow = rangeWindow(r)
  if (!zoomWindow) return
  applyingRange = true
  chart.value?.dispatchAction({
    type: 'dataZoom',
    startValue: zoomWindow.start,
    endValue: zoomWindow.end,
  })
  applyingRange = false
}

function onDataZoom() {
  const zoom = (chart.value?.getOption() as any)?.dataZoom?.[0]
  if (zoom?.startValue == null || zoom?.endValue == null) return
  zoomWindow = { start: Number(zoom.startValue), end: Number(zoom.endValue) }
  zoomPercent.value = { start: Number(zoom.start), end: Number(zoom.end) }
  measureTrack()
  if (!applyingRange && range.value !== null) range.value = null
}

const tabPercent = computed(() => {
  if (zoomPercent.value) return zoomPercent.value
  const w = rangeWindow(initialRange)
  const e = extent.value
  if (!w || !e || e.max === e.min) return { start: 0, end: 100 }
  return {
    start: ((w.start - e.min) / (e.max - e.min)) * 100,
    end: ((w.end - e.min) / (e.max - e.min)) * 100,
  }
})

const tabStyle = computed(() => {
  const { start, end } = tabPercent.value
  if (!track.value) return { display: 'none' }
  const t = track.value
  let left = t.left + (t.width * start) / 100 + HANDLE_INSET
  let width = (t.width * (end - start)) / 100 - 2 * HANDLE_INSET
  if (width < MIN_TAB_WIDTH) {
    const lo = t.left + HANDLE_INSET
    const hi = t.left + t.width - HANDLE_INSET - MIN_TAB_WIDTH
    left = Math.min(Math.max(left + width / 2 - MIN_TAB_WIDTH / 2, lo), hi)
    width = MIN_TAB_WIDTH
  }
  return { left: `${left}px`, width: `${width}px` }
})

function dragTab(down: PointerEvent) {
  const tab = down.currentTarget as HTMLElement
  const trackWidth = track.value?.width ?? 1
  const from = { x: down.clientX, ...tabPercent.value }
  tab.setPointerCapture(down.pointerId)
  const move = (e: PointerEvent) => {
    const shift = Math.min(
      Math.max(((e.clientX - from.x) / trackWidth) * 100, -from.start),
      100 - from.end,
    )
    chart.value?.dispatchAction({
      type: 'dataZoom',
      start: from.start + shift,
      end: from.end + shift,
    })
  }
  const up = () => {
    tab.removeEventListener('pointermove', move)
    tab.removeEventListener('pointerup', up)
    tab.removeEventListener('pointercancel', up)
  }
  tab.addEventListener('pointermove', move)
  tab.addEventListener('pointerup', up)
  tab.addEventListener('pointercancel', up)
}

function showHours() {
  const w = zoomWindow ?? rangeWindow(initialRange)
  return !!w && props.hourly && w.end - w.start <= 2 * DAY_MS
}

function formatDate(value: number, options: Intl.DateTimeFormatOptions) {
  return new Date(value).toLocaleString('en-US', options)
}

const option = computed<EChartsOption>(() => {
  const byName = [...props.lines].sort((a, b) => a.name.localeCompare(b.name))
  const series: SeriesOption[] = byName.map((line, i) => ({
    type: 'line',
    name: line.name,
    color: LINE_COLORS[i % LINE_COLORS.length],
    data: line.points,
    showSymbol: false,
    connectNulls: true,
    sampling: 'lttb',
    emphasis: { focus: 'series' },
  }))
  series.push({
    type: 'line',
    silent: true,
    data: [],
    markLine: {
      animation: false,
      emphasis: { disabled: true },
      silent: true,
      symbol: 'none',
      lineStyle: { color: 'grey', type: 'dashed' },
      label: { show: true, formatter: '{b}', position: 'insideStartTop' },
      data: props.milestones.map((m) => ({
        xAxis: new Date(`${m.date}T00:00:00`).getTime(),
        name: m.description,
      })),
    },
  })

  const step = props.yStep
  const shown = zoomWindow ?? rangeWindow(initialRange)
  return {
    animation: reducedMotion.value !== 'reduce',
    backgroundColor: 'transparent',
    series,
    tooltip: {
      backgroundColor: '',
      borderWidth: 0,
      textStyle: undefined,
      trigger: 'axis',
      className: 'p-card',
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const header = formatDate(
          params[0].axisValue,
          props.hourly
            ? { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }
            : { month: 'short', day: 'numeric' },
        )
        const lines = params
          .filter((p: any) => p.value?.[1] != null)
          .sort((a: any, b: any) => b.value[1] - a.value[1])
          .map((p: any) => `${p.marker}${p.seriesName}: ${props.formatValue(p.value[1])}`)
        return [header, ...lines].join('<br/>')
      },
    },
    legend: {
      data: props.lines.map((l) => l.name),
      icon: 'circle',
      top: 'top',
      left: 'center',
      width: isPhone.value ? '75%' : '85%',
      textStyle: { fontSize: isPhone.value ? 17 : 14 },
    },
    grid: {
      left: 'left',
      right: 16,
      top: isPhone.value ? 110 : '15%',
      bottom: 64,
      containLabel: true,
    },
    dataZoom: {
      type: 'slider',
      filterMode: 'weakFilter',
      startValue: shown?.start,
      endValue: shown?.end,
      minValueSpan: props.hourly ? 6 * 60 * 60 * 1000 : 7 * DAY_MS,
      left: SLIDER_INSET,
      right: SLIDER_INSET,
      bottom: 20,
      height: 28,
      brushSelect: false,
      backgroundColor: TRACK_MARKER,
      showDetail: false,
    },
    toolbox: {
      show: !isPhone.value,
      itemSize: 20,
      right: 0,
      feature: {
        saveAsImage: { show: true, title: 'Save', excludeComponents: ['toolbox', 'dataZoom'] },
      },
    },
    xAxis: {
      type: 'time',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        margin: 10,
        hideOverlap: true,
        formatter: (value: number) =>
          ` ${formatDate(value, showHours() ? { hour: 'numeric' } : { month: 'numeric', day: 'numeric' })} `,
      },
      axisPointer: {
        label: {
          formatter: (params: any) =>
            formatDate(
              Number(params.value),
              props.hourly
                ? { month: 'short', day: 'numeric', hour: 'numeric' }
                : { month: 'short', day: 'numeric', year: 'numeric' },
            ),
        },
      },
    },
    yAxis: {
      type: 'value',
      scale: props.yMin === undefined,
      ...(props.yMin !== undefined && { min: props.yMin }),
      ...(step && { max: (v: { max: number }) => Math.max(step, Math.ceil(v.max / step) * step) }),
      ...(props.formatAxisValue && { axisLabel: { formatter: props.formatAxisValue } }),
    },
  }
})

watch(
  () => props.ranges,
  (ranges) => {
    if (range.value && !ranges.includes(range.value)) selectRange('ALL')
  },
)
</script>

<template>
  <div class="flex flex-col gap-2">
    <div ref="chartBox" class="relative">
      <v-chart
        ref="chart"
        :option="option"
        theme="dark"
        class="w-full min-h-[400px]"
        autoresize
        @datazoom="onDataZoom"
        @finished="measureTrack"
      />
      <div
        class="absolute bottom-0 h-5 flex items-center justify-center gap-0.5 rounded-b-md bg-surface-500/60 hover:bg-surface-400/70 cursor-grab active:cursor-grabbing touch-none select-none"
        :style="tabStyle"
        aria-hidden="true"
        @pointerdown.prevent="dragTab"
      >
        <span v-for="i in 3" :key="i" class="h-2.5 w-0.5 rounded-full bg-white/90" />
      </div>
    </div>
    <div class="flex justify-center gap-1" role="group" aria-label="Time range">
      <Button
        v-for="r in props.ranges"
        :key="r"
        :label="r"
        size="small"
        variant="outlined"
        :severity="range === r ? 'primary' : 'secondary'"
        :aria-pressed="range === r"
        class="h-8 px-2 shrink-0"
        @click="selectRange(r)"
      />
    </div>
  </div>
</template>
