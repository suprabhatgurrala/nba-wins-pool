import { ref } from 'vue'
import type { WinsRaceData } from '@/types/winsRace'

export function useWinsRaceData() {
  const winsRaceData = ref<WinsRaceData | null>(null)

  function setWinsRaceData(data: WinsRaceData | null) {
    winsRaceData.value = data
  }

  return { winsRaceData, setWinsRaceData }
}
