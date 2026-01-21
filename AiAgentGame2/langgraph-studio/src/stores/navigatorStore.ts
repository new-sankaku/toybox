import { create } from 'zustand'

export type MessageSource = 'client' | 'server'
export type MessagePriority = 'low' | 'normal' | 'high' | 'critical'

export interface NavigatorMessage {
  id: string
  speaker: string
  text: string
  timestamp: number
  source: MessageSource
  priority: MessagePriority
}

interface NavigatorState {
  isVisible: boolean
  currentMessage: NavigatorMessage | null
  messageQueue: NavigatorMessage[]
  // Client-side message (for UI navigation, local events)
  showMessage: (speaker: string, text: string) => void
  // Server-side message (for important notifications from backend)
  showServerMessage: (speaker: string, text: string, priority?: MessagePriority) => void
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
      timestamp: Date.now(),
      source: 'client',
      priority: 'normal'
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

  showServerMessage: (speaker: string, text: string, priority: MessagePriority = 'normal') => {
    const message: NavigatorMessage = {
      id: `srv-${Date.now()}`,
      speaker,
      text,
      timestamp: Date.now(),
      source: 'server',
      priority
    }

    const state = get()

    // High/critical priority messages jump to front of queue
    if (priority === 'critical' || priority === 'high') {
      if (state.currentMessage) {
        // Insert at front of queue, will show after current message is dismissed
        set({ messageQueue: [message, ...state.messageQueue] })
      } else {
        set({ isVisible: true, currentMessage: message })
      }
    } else {
      // Normal/low priority - add to end of queue
      if (state.currentMessage) {
        set({ messageQueue: [...state.messageQueue, message] })
      } else {
        set({ isVisible: true, currentMessage: message })
      }
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
