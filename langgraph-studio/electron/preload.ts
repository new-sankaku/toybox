import { contextBridge, ipcRenderer } from 'electron'

// Custom APIs for renderer
const api = {
  // Backend management
  backend: {
    start: (): Promise<{ success: boolean; port?: number; error?: string }> =>
      ipcRenderer.invoke('backend:start'),
    stop: (): Promise<{ success: boolean }> =>
      ipcRenderer.invoke('backend:stop'),
    status: (): Promise<{ running: boolean; port: number | null }> =>
      ipcRenderer.invoke('backend:status'),
    getPort: (): Promise<number | null> =>
      ipcRenderer.invoke('backend:port')
  },

  // App info
  app: {
    getVersion: (): Promise<string> =>
      ipcRenderer.invoke('app:version'),
    getPlatform: (): Promise<NodeJS.Platform> =>
      ipcRenderer.invoke('app:platform')
  },

  // Event listeners for backend status changes
  on: (channel: string, callback: (...args: unknown[]) => void): void => {
    const validChannels = [
      'backend:ready',
      'backend:error',
      'backend:stopped'
    ]
    if (validChannels.includes(channel)) {
      ipcRenderer.on(channel, (_event, ...args) => callback(...args))
    }
  },

  off: (channel: string, callback: (...args: unknown[]) => void): void => {
    ipcRenderer.removeListener(channel, callback)
  }
}

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = api
}

// Type declarations
export type ElectronAPI = typeof api
