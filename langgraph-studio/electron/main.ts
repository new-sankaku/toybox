import { app, shell, BrowserWindow, ipcMain } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { BackendManager } from './backend/manager'

// Fix GPU cache errors on Windows
// Set custom cache path before app is ready
const userDataPath = app.getPath('userData')
app.setPath('sessionData', join(userDataPath, 'session'))
app.commandLine.appendSwitch('disk-cache-dir', join(userDataPath, 'cache'))
app.commandLine.appendSwitch('gpu-cache-dir', join(userDataPath, 'gpu-cache'))

let mainWindow: BrowserWindow | null = null
let backendManager: BackendManager | null = null

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1200,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#E8E4D4', // NieR background
    title: 'LangGraph Studio',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // HMR for renderer based on electron-vite cli
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// IPC Handlers
function setupIpcHandlers(): void {
  // Backend management
  ipcMain.handle('backend:start', async () => {
    if (!backendManager) {
      backendManager = new BackendManager()
    }
    return await backendManager.start()
  })

  ipcMain.handle('backend:stop', async () => {
    if (backendManager) {
      await backendManager.stop()
    }
    return { success: true }
  })

  ipcMain.handle('backend:status', () => {
    if (!backendManager) {
      return { running: false, port: null }
    }
    return backendManager.getStatus()
  })

  ipcMain.handle('backend:port', () => {
    return backendManager?.getPort() ?? null
  })

  // App info
  ipcMain.handle('app:version', () => {
    return app.getVersion()
  })

  ipcMain.handle('app:platform', () => {
    return process.platform
  })
}

// App lifecycle
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.langgraph.studio')

  // Default open or close DevTools by F12 in development
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  setupIpcHandlers()
  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', async () => {
  // Stop backend before quitting
  if (backendManager) {
    await backendManager.stop()
  }

  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error)
})
