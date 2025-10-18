import { ref } from 'vue'

/**
 * Composable for playing audio files
 */
export function useAudio() {
  const isPlaying = ref(false)
  const error = ref<string | null>(null)

  /**
   * Play an audio file from a URL or path
   * @param audioPath - Path to the audio file (relative to public folder or absolute URL)
   * @param volume - Volume level (0.0 to 1.0), defaults to 1.0
   */
  const playSound = async (audioPath: string, volume = 1.0): Promise<void> => {
    error.value = null
    try {
      const audio = new Audio(audioPath)
      audio.volume = Math.max(0, Math.min(1, volume))
      
      isPlaying.value = true
      
      // Wait for audio to finish playing
      await new Promise<void>((resolve, reject) => {
        audio.onended = () => {
          isPlaying.value = false
          resolve()
        }
        audio.onerror = () => {
          isPlaying.value = false
          error.value = 'Failed to load or play audio'
          reject(new Error('Audio playback failed'))
        }
        audio.play().catch((err) => {
          isPlaying.value = false
          error.value = err.message || 'Failed to play audio'
          reject(err)
        })
      })
    } catch (err: any) {
      isPlaying.value = false
      error.value = err?.message || 'Failed to play audio'
      console.error('Audio playback error:', err)
    }
  }

  /**
   * Play the NBA draft sound effect
   */
  const playDraftSound = async (volume = 0.7): Promise<void> => {
    // Using the classic NBA draft sound
    // This is hosted publicly - you can replace with your own file in /public/sounds/
    await playSound('/sounds/nba-draft.mp3', volume)
  }

  /**
   * Play a short notification ding sound
   */
  const playDing = async (volume = 0.3): Promise<void> => {
    // Short, subtle notification sound for auction updates
    await playSound('/sounds/notification-ding.mp3', volume)
  }

  return {
    isPlaying,
    error,
    playSound,
    playDraftSound,
    playDing,
  }
}
