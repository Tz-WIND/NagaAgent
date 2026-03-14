export type FloatingState = 'classic' | 'ball' | 'compact' | 'full'

export interface CaptureSource {
  id: string
  name: string
  thumbnail: string
  appIcon: string | null
}

export interface CaptureAPI {
  getSources: () => Promise<CaptureSource[] | { permission: string }>
  captureWindow: (sourceId: string) => Promise<string | null>
  openScreenSettings: () => Promise<void>
}

export interface BackendAPI {
  getLogs: () => Promise<string>
  onProgress: (callback: (payload: { percent: number, phase: string }) => void) => () => void
  onLog: (callback: (payload: { line: string }) => void) => () => void
  onError: (callback: (payload: { code: number, logs: string }) => void) => () => void
}

export interface FloatingAPI {
  enter: () => Promise<void>
  exit: () => Promise<void>
  expand: (toFull?: boolean) => Promise<void>
  expandToFull: () => Promise<void>
  collapse: () => Promise<void>
  collapseToCompact: () => Promise<void>
  getState: () => Promise<FloatingState>
  pin: (value: boolean) => void
  fitHeight: (height: number) => void
  setPosition: (x: number, y: number) => void
  onStateChange: (callback: (state: FloatingState) => void) => () => void
  onWindowBlur: (callback: () => void) => () => void
}

export interface BackgroundsAPI {
  scan: () => Promise<string[]>
}

export interface AutoLaunchAPI {
  get: () => Promise<boolean>
  set: (enabled: boolean) => Promise<void>
}

export interface ElectronAPI {
  minimize: () => void
  maximize: () => void
  close: () => void
  isMaximized: () => Promise<boolean>
  getBounds: () => Promise<{ x: number, y: number, width: number, height: number }>
  setBounds: (bounds: { x?: number, y?: number, width?: number, height?: number }) => void
  quit: () => void
  showContextMenu: () => void
  onMaximized: (callback: (maximized: boolean) => void) => () => void
  downloadUpdate: () => void
  installUpdate: () => void
  onUpdateAvailable: (callback: (info: { version: string, releaseNotes: string }) => void) => () => void
  onUpdateDownloaded: (callback: () => void) => () => void
  floating: FloatingAPI
  capture: CaptureAPI
  backend: BackendAPI
  backgrounds: BackgroundsAPI
  autoLaunch: AutoLaunchAPI
  platform: string
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
