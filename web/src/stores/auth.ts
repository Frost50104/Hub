import { create } from 'zustand'

type AuthState = {
  status: 'idle' | 'authenticating' | 'authenticated' | 'error'
  error: string | null
  setStatus: (s: AuthState['status']) => void
  setError: (e: string | null) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'idle',
  error: null,
  setStatus: (status) => set({ status }),
  setError: (error) => set({ error }),
}))
