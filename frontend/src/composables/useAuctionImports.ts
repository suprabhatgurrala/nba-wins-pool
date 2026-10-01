import { ref } from 'vue'

async function postBatch(url: string, body: object, failure: string): Promise<unknown> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let message = `${failure} (HTTP ${res.status})`
    try {
      const data = await res.json()
      message = data?.detail || message
    } catch (_) {}
    throw new Error(message)
  }
  return res.json()
}

export function addPoolRosters(auctionId: string): Promise<unknown> {
  // NOTE: Backend expects auction to be in draft status for participant import.
  return postBatch(
    '/api/auction-participants/batch',
    { source: 'pool', auction_id: auctionId },
    'Failed to import participants',
  )
}

export function addNbaTeams(auctionId: string): Promise<unknown> {
  // NOTE: Backend expects league slug to be lowercase (e.g., "nba").
  return postBatch(
    '/api/auction-lots/batch',
    { source: 'league', source_id: 'nba', auction_id: auctionId },
    'Failed to import lots',
  )
}

export function useAuctionImports(auctionId: string, onImported: () => Promise<void> | void) {
  const importParticipantsSubmitting = ref(false)
  const importParticipantsError = ref<string | null>(null)
  const importParticipantsMessage = ref<string | null>(null)
  const importLotsSubmitting = ref(false)
  const importLotsError = ref<string | null>(null)
  const importLotsMessage = ref<string | null>(null)

  async function handleImportParticipants() {
    importParticipantsSubmitting.value = true
    importParticipantsError.value = null
    importParticipantsMessage.value = null
    try {
      const imported = await addPoolRosters(auctionId)
      if (Array.isArray(imported)) {
        const count = imported.length
        importParticipantsMessage.value = count
          ? `Imported ${count} participant${count === 1 ? '' : 's'} from pool rosters.`
          : 'No new participants were added.'
      } else {
        importParticipantsMessage.value = 'Imported participants from pool rosters.'
      }
      await onImported()
    } catch (e: any) {
      importParticipantsError.value = e?.message || 'Failed to import participants'
    } finally {
      importParticipantsSubmitting.value = false
    }
  }

  async function handleImportLotsFromLeague() {
    importLotsSubmitting.value = true
    importLotsError.value = null
    importLotsMessage.value = null
    try {
      const added = await addNbaTeams(auctionId)
      if (Array.isArray(added)) {
        const count = added.length
        importLotsMessage.value = count
          ? `Imported ${count} lot${count === 1 ? '' : 's'} from the NBA.`
          : 'No new lots were added (all teams already present).'
      } else {
        importLotsMessage.value = 'Imported league lots into the auction.'
      }
      await onImported()
    } catch (e: any) {
      importLotsError.value = e?.message || 'Failed to import league lots'
    } finally {
      importLotsSubmitting.value = false
    }
  }

  return {
    importParticipantsSubmitting,
    importParticipantsError,
    importParticipantsMessage,
    importLotsSubmitting,
    importLotsError,
    importLotsMessage,
    handleImportParticipants,
    handleImportLotsFromLeague,
  }
}
