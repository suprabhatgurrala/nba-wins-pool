<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useColorMode } from '@vueuse/core'
import { use } from 'echarts/core'
import type { EChartsOption, SeriesOption } from 'echarts'
import Card from 'primevue/card'
import VChart from 'vue-echarts'
import type { WinsRaceData } from '@/types/pool'

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
  const milestones = metadata.milestones

  const dataset = [
    { id: 'raw', source: rawData },
    ...metadata.owners.map((owner) => ({
      id: owner.name,
      fromDatasetId: 'raw',
      transform: {
        type: 'filter',
        config: { dimension: 'owner', value: owner.name },
      },
    })),
  ]
  const series: SeriesOption[] = metadata.owners.map((owner) => ({
    type: 'line',
    name: owner.name,
    encode: {
      x: 'date',
      y: 'wins',
    },
    datasetId: owner.name,
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
        xAxis: milestone.date,
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
      order: 'valueDesc',
      trigger: 'axis',
      className: 'p-card',
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
      minSpan: 7,
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
      type: 'category',
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        margin: 10,
        formatter: (value: string) => {
          const date = new Date(`${value}T00:00:00`)
          return date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' })
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
            startValue: 100,
            minValueSpan: 14,
          },
          legend: {
            width: '75%',
            textStyle: {
              fontSize: 17,
            },
          },
          grid: {},
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
  <Card>
    <template #content>
      <v-chart :option="chartOption" :theme="colorMode" class="wins-chart" autoresize />
    </template>
  </Card>
</template>

<style scoped>
.wins-chart {
  width: 80vw;
  min-height: 40vh;
  max-width: 768px;
}

@media (max-width: 768px) {
  .wins-chart {
    min-width: calc((100vw - 4rem));
    min-height: 55vh;
  }
}
</style>
