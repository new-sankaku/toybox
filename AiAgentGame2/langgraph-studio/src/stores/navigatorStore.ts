import { create } from 'zustand'

export interface NavigatorMessage {
  id: string
  speaker: string
  text: string
  timestamp: number
}

interface NavigatorState {
  isVisible: boolean
  currentMessage: NavigatorMessage | null
  messageQueue: NavigatorMessage[]
  showMessage: (speaker: string, text: string) => void
  dismissMessage: () => void
  clearAll: () => void
}

export const useNavigatorStore = create<NavigatorState>((set, get) => ({
  isVisible: false,
  currentMessage: null,
  messageQueue: [],

  showMessage: (speaker: string, text: string) => {
    const message: NavigatorMessage = {
      id: `msg-${Date.now()}`,
      speaker,
      text,
      timestamp: Date.now()
    }

    const state = get()
    if (state.currentMessage) {
      // Queue the message if one is already showing
      set({ messageQueue: [...state.messageQueue, message] })
    } else {
      // Show immediately
      set({ isVisible: true, currentMessage: message })
    }
  },

  dismissMessage: () => {
    const state = get()
    if (state.messageQueue.length > 0) {
      // Show next message from queue
      const [nextMessage, ...remainingQueue] = state.messageQueue
      set({
        currentMessage: nextMessage,
        messageQueue: remainingQueue
      })
    } else {
      // Hide navigator when no more messages
      set({ isVisible: false, currentMessage: null })
    }
  },

  clearAll: () => {
    set({ isVisible: false, currentMessage: null, messageQueue: [] })
  }
}))
