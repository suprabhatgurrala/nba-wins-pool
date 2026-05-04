<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useColorMode } from '@vueuse/core'
import { use } from 'echarts/core'
import type { EChartsOption, SeriesOption } from 'echarts'
import Card from 'primevue/card'
import VChart from 'vue-echarts'
import type { WinsRaceData } from '@/types/winsRace'

import {
  DatasetComponent,
  TooltipComponent,
  TransformComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
  ToolboxComponent,
  MarkLineComponent,
} from 'echarts/components'

import { LineChart } from 'echarts/charts'
import { LabelLayout, UniversalTransition } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'

// Register ECharts components
use([
  DatasetComponent,
  DataZoomComponent,
  TooltipComponent,
  GridComponent,
  TransformComponent,
  LegendComponent,
  LineChart,
  MarkLineComponent,
  SVGRenderer,
  LabelLayout,
  UniversalTransition,
  ToolboxComponent,
])

const props = defineProps<{
  winsRaceData: WinsRaceData | null
}>()

const chartOption = ref<EChartsOption>({})
const colorMode = useColorMode()

const updateChartData = () => {
  if (!props.winsRaceData) return

  const rawData = props.winsRaceData.data
  const metadata = props.winsRaceData.metadata
  const milestones = metadata?.milestones

  const maxDateStr = rawData.reduce((max: string, d: any) => (d.date > max ? d.date : max), '')
  const endTs = maxDateStr ? new Date(`${maxDateStr}T00:00:00`).getTime() : Date.now()
  const startTs30d = endTs - 30 * 24 * 60 * 60 * 1000

  if (!milestones || !metadata?.rosters) return

  const dataset = [
    { id: 'raw', source: rawData },
    ...metadata.rosters.map((roster) => ({
      id: roster.name,
      fromDatasetId: 'raw',
      transform: {
        type: 'filter',
        config: { dimension: 'roster', value: roster.name },
      },
    })),
  ] as any
  const series: SeriesOption[] = metadata.rosters.map((roster) => ({
    type: 'line',
    name: roster.name,
    encode: {
      x: 'date',
      y: 'wins',
    },
    datasetId: roster.name,
    showSymbol: false,
    emphasis: { focus: 'series' },
  }))

  // Add milestone markers as an invisible series
  series.push({
    type: 'line',
    silent: true,
    data: [],
    markLine: {
      animation: false,
      emphasis: {
        disabled: true,
      },
      silent: true,
      symbol: 'none',
      lineStyle: {
        color: 'grey',
        type: 'dashed',
      },
      label: {
        show: true,
        formatter: '{b}',
        position: 'insideStartTop',
      },
      data: milestones.map((milestone) => ({
        xAxis: new Date(`${milestone.date}T00:00:00`).getTime(),
        name: milestone.description,
      })),
    },
  })

  chartOption.value = {
    dataset: dataset,
    series: series,
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: '',
      borderWidth: 0,
      textStyle: undefined,
      trigger: 'axis',
      className: 'p-card',
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const header = new Date(params[0].axisValue).toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
        })
        const lines = params
          .filter((p: any) => p.value?.wins != null)
          .sort((a: any, b: any) => b.value.wins - a.value.wins)
          .map((p: any) => `${p.marker}${p.seriesName}: ${p.value.wins}`)
        return [header, ...lines].join('<br/>')
      },
    },
    legend: {
      icon: 'circle',
      top: 'top',
      textStyle: {
        fontSize: 14,
      },
    },
    grid: {
      left: 'left',
      right: 0,
      top: '15%',
      bottom: 60,
      containLabel: true,
    },
    dataZoom: {
      type: 'slider',
      filterMode: 'weakFilter',
      minValueSpan: 7 * 24 * 60 * 60 * 1000,
      left: 'center',
      moveHandleSize: 15,
      labelFormatter: '',
    },
    toolbox: {
      itemSize: 20,
      left: 'right',
      feature: {
        dataZoom: {
          show: true,
          title: {
            zoom: 'Zoom Select',
            back: 'Undo Zoom',
          },
          yAxisIndex: false,
        },
        restore: {
          show: true,
          title: 'Reset',
        },
        saveAsImage: {
          show: true,
          title: 'Save',
          excludeComponents: ['toolbox', 'dataZoom'],
        },
      },
    },
    xAxis: {
      type: 'time',
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        margin: 10,
        formatter: (value: number) => {
          const date = new Date(value)
          return date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' })
        },
      },
      axisPointer: {
        label: {
          formatter: (params: any) =>
            new Date(Number(params.value)).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
        },
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
    },
    media: [
      {
        query: {
          maxWidth: 650,
        },
        option: {
          toolbox: {
            show: false,
            top: 'bottom',
            left: 'center',
          },
          dataZoom: {
            throttle: 50,
            startValue: startTs30d,
            endValue: endTs,
            minValueSpan: 14 * 24 * 60 * 60 * 1000,
          },
          legend: {
            width: '75%',
            textStyle: {
              fontSize: 17,
            },
          },
        },
      },
    ],
  }
}

watch(
  () => props.winsRaceData,
  () => {
    updateChartData()
  },
  { immediate: true },
)

onMounted(() => {
  // Lets chart's media query handle resizing
  window.addEventListener('resize', updateChartData)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateChartData)
})
</script>

<template>
  <div
    v-if="props.winsRaceData && props.winsRaceData.data.length > 0"
    class="w-full overflow-x-auto"
  >
    <v-chart
      :option="chartOption"
      :theme="colorMode"
      class="w-full min-h-[400px] md:min-h-[400px]"
      autoresize
    />
  </div>
  <p
    v-else-if="props.winsRaceData && props.winsRaceData.data.length === 0"
    class="text-surface-400"
    role="alert"
  >
    No data available
  </p>
  <p v-else class="text-surface-400" role="alert">Chart could not be loaded.</p>
</template>
