import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join } from 'path'
import * as net from 'net'

export class BackendManager {
  private process: ChildProcess | null = null
  private port: number | null = null
  private isRunning = false
  private healthCheckInterval: NodeJS.Timeout | null = null

  constructor() {}

  /**
   * Find an available port starting from the default
   */
  private async findAvailablePort(startPort = 8765): Promise<number> {
    return new Promise((resolve, reject) => {
      const server = net.createServer()
      server.listen(startPort, () => {
        const { port } = server.address() as net.AddressInfo
        server.close(() => resolve(port))
      })
      server.on('error', () => {
        // Port in use, try next
        if (startPort < 65535) {
          resolve(this.findAvailablePort(startPort + 1))
        } else {
          reject(new Error('No available port found'))
        }
      })
    })
  }

  /**
   * Check if backend is healthy
   */
  private async healthCheck(): Promise<boolean> {
    if (!this.port) return false

    return new Promise((resolve) => {
      const timeout = setTimeout(() => resolve(false), 2000)

      fetch(`http://localhost:${this.port}/health`)
        .then((res) => {
          clearTimeout(timeout)
          resolve(res.ok)
        })
        .catch(() => {
          clearTimeout(timeout)
          resolve(false)
        })
    })
  }

  /**
   * Wait for backend to be ready
   */
  private async waitForReady(maxAttempts = 30, intervalMs = 500): Promise<boolean> {
    for (let i = 0; i < maxAttempts; i++) {
      if (await this.healthCheck()) {
        return true
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs))
    }
    return false
  }

  /**
   * Start the Python backend
   */
  async start(): Promise<{ success: boolean; port?: number; error?: string }> {
    if (this.isRunning && this.process) {
      return { success: true, port: this.port ?? undefined }
    }

    try {
      // Find available port
      this.port = await this.findAvailablePort()

      // Determine Python command based on platform
      const pythonCmd = process.platform === 'win32' ? 'python' : 'python3'

      // Backend path - in development vs production
      const isDev = !app.isPackaged
      const backendPath = isDev
        ? join(__dirname, '../../..', 'backend')
        : join(process.resourcesPath, 'backend')

      console.log(`Starting backend at ${backendPath} on port ${this.port}`)

      // Spawn Python process
      this.process = spawn(
        pythonCmd,
        [
          '-m',
          'uvicorn',
          'app.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          this.port.toString(),
          '--reload'
        ],
        {
          cwd: backendPath,
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1'
          },
          stdio: ['ignore', 'pipe', 'pipe']
        }
      )

      // Log output
      this.process.stdout?.on('data', (data) => {
        console.log(`[Backend] ${data.toString().trim()}`)
      })

      this.process.stderr?.on('data', (data) => {
        console.error(`[Backend Error] ${data.toString().trim()}`)
      })

      this.process.on('error', (error) => {
        console.error('Failed to start backend:', error)
        this.isRunning = false
      })

      this.process.on('exit', (code) => {
        console.log(`Backend exited with code ${code}`)
        this.isRunning = false
        this.process = null
      })

      // Wait for backend to be ready
      const ready = await this.waitForReady()

      if (ready) {
        this.isRunning = true
        this.startHealthCheckInterval()
        return { success: true, port: this.port }
      } else {
        await this.stop()
        return { success: false, error: 'Backend failed to start' }
      }
    } catch (error) {
      console.error('Error starting backend:', error)
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error'
      }
    }
  }

  /**
   * Stop the Python backend
   */
  async stop(): Promise<void> {
    this.stopHealthCheckInterval()

    if (this.process) {
      return new Promise((resolve) => {
        if (!this.process) {
          resolve()
          return
        }

        this.process.on('exit', () => {
          this.process = null
          this.isRunning = false
          this.port = null
          resolve()
        })

        // Try graceful shutdown first
        if (process.platform === 'win32') {
          this.process.kill()
        } else {
          this.process.kill('SIGTERM')

          // Force kill after timeout
          setTimeout(() => {
            if (this.process) {
              this.process.kill('SIGKILL')
            }
          }, 5000)
        }
      })
    }
  }

  /**
   * Start periodic health checks
   */
  private startHealthCheckInterval(): void {
    this.healthCheckInterval = setInterval(async () => {
      const healthy = await this.healthCheck()
      if (!healthy && this.isRunning) {
        console.warn('Backend health check failed')
        // Could implement auto-restart here
      }
    }, 30000) // Check every 30 seconds
  }

  /**
   * Stop health check interval
   */
  private stopHealthCheckInterval(): void {
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
      this.healthCheckInterval = null
    }
  }

  /**
   * Get current status
   */
  getStatus(): { running: boolean; port: number | null } {
    return {
      running: this.isRunning,
      port: this.port
    }
  }

  /**
   * Get backend port
   */
  getPort(): number | null {
    return this.port
  }
}
