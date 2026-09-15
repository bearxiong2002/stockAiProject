import { create } from 'zustand'
import { getHealth, BackendStatus } from '@/services/api'
import type { HealthResponse } from '@/services/api'

interface BackendStore {
  status: BackendStatus
  health: HealthResponse | null
  probeOnce: (timeoutMs?: number) => Promise<boolean>
}

export const useBackendStore = create<BackendStore>((set) => ({
  status: 'connecting',
  health: null,

  probeOnce: async (timeoutMs = 30000) => {
    const startedAt = Date.now()
    while (true) {
      try {
        const health = await getHealth()
        set({ status: 'ready', health })
        return true
      } catch {
        if (Date.now() - startedAt > timeoutMs) {
          set({ status: 'error' })
          return false
        }
        await new Promise((r) => setTimeout(r, 800))
      }
    }
  }
}))
