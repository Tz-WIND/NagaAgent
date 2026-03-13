import { contextBridge, ipcRenderer } from 'electron'

function detectPlatform(): 'darwin' | 'win32' | 'linux' | 'unknown' {
  const uaDataPlatform = (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform
  const parts = [
    uaDataPlatform,
    navigator.platform,
    navigator.userAgent,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  if (parts.includes('mac'))
    return 'darwin'
  if (parts.includes('win'))
    return 'win32'
  if (parts.includes('linux'))
    return 'linux'
  return 'unknown'
}

const electronAPI = {
  // Window controls
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
  getBounds: () => ipcRenderer.invoke('window:getBounds') as Promise<{ x: number, y: number, width: number, height: number }>,
  setBounds: (bounds: { x?: number, y?: number, width?: number, height?: number }) => ipcRenderer.send('window:setBounds', bounds),
  quit: () => ipcRenderer.send('app:quit'),
  showContextMenu: () => ipcRenderer.send('context-menu:show'),

  // Window state events
  onMaximized: (callback: (maximized: boolean) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, maximized: boolean) => callback(maximized)
    ipcRenderer.on('window:maximized', handler)
    return () => ipcRenderer.removeListener('window:maximized', handler)
  },

  // Updater
  downloadUpdate: () => ipcRenderer.send('updater:download'),
  installUpdate: () => ipcRenderer.send('updater:install'),

  onUpdateAvailable: (callback: (info: { version: string, releaseNotes: string }) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, info: { version: string, releaseNotes: string }) => callback(info)
    ipcRenderer.on('updater:update-available', handler)
    return () => ipcRenderer.removeListener('updater:update-available', handler)
  },
  onUpdateDownloaded: (callback: () => void) => {
    const handler = () => callback()
    ipcRenderer.on('updater:update-downloaded', handler)
    return () => ipcRenderer.removeListener('updater:update-downloaded', handler)
  },

  // 悬浮球模式控制
  floating: {
    enter: () => ipcRenderer.invoke('floating:enter'),
    exit: () => ipcRenderer.invoke('floating:exit'),
    expand: (toFull?: boolean) => ipcRenderer.invoke('floating:expand', toFull),
    expandToFull: () => ipcRenderer.invoke('floating:expandToFull'),
    collapse: () => ipcRenderer.invoke('floating:collapse'),
    collapseToCompact: () => ipcRenderer.invoke('floating:collapseToCompact'),
    getState: () => ipcRenderer.invoke('floating:getState') as Promise<'classic' | 'ball' | 'compact' | 'full'>,
    pin: (value: boolean) => ipcRenderer.send('floating:pin', value),
    fitHeight: (height: number) => ipcRenderer.send('floating:fitHeight', height),
    setPosition: (x: number, y: number) => ipcRenderer.send('floating:setPosition', x, y),
    onStateChange: (callback: (state: 'classic' | 'ball' | 'compact' | 'full') => void) => {
      const handler = (_event: Electron.IpcRendererEvent, state: 'classic' | 'ball' | 'compact' | 'full') => callback(state)
      ipcRenderer.on('floating:stateChanged', handler)
      return () => ipcRenderer.removeListener('floating:stateChanged', handler)
    },
    onWindowBlur: (callback: () => void) => {
      const handler = () => callback()
      ipcRenderer.on('floating:windowBlur', handler)
      return () => ipcRenderer.removeListener('floating:windowBlur', handler)
    },
  },

  // 窗口截屏功能
  capture: {
    getSources: () => ipcRenderer.invoke('capture:getSources') as Promise<
      | { permission: string }
      | Array<{ id: string, name: string, thumbnail: string, appIcon: string | null }>
    >,
    captureWindow: (sourceId: string) => ipcRenderer.invoke('capture:captureWindow', sourceId) as Promise<string | null>,
    openScreenSettings: () => ipcRenderer.invoke('capture:openScreenSettings') as Promise<void>,
  },

  // 后端进程通信
  backend: {
    onProgress: (callback: (payload: { percent: number, phase: string }) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, payload: { percent: number, phase: string }) => callback(payload)
      ipcRenderer.on('backend:progress', handler)
      return () => ipcRenderer.removeListener('backend:progress', handler)
    },
    onError: (callback: (payload: { code: number, logs: string }) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, payload: { code: number, logs: string }) => callback(payload)
      ipcRenderer.on('backend:error', handler)
      return () => ipcRenderer.removeListener('backend:error', handler)
    },
  },

  // 背景图片扫描
  backgrounds: {
    scan: () => ipcRenderer.invoke('backgrounds:scan') as Promise<string[]>,
  },

  // 开机自启动
  autoLaunch: {
    get: () => ipcRenderer.invoke('autoLaunch:get') as Promise<boolean>,
    set: (enabled: boolean) => ipcRenderer.invoke('autoLaunch:set', enabled) as Promise<void>,
  },

  // 热补丁系统
  patcher: {
    getStatus: () => ipcRenderer.invoke('patcher:getStatus') as Promise<{
      patchVersion: string | null
      appliedAt: string | null
      source: string | null
      official: boolean
      patchDir: string
      fileCount: number
    }>,
    checkUpdate: (serverUrl: string) => ipcRenderer.invoke('patcher:checkUpdate', serverUrl) as Promise<{
      updated: boolean
      version?: string
      frontendChanged: boolean
      backendChanged: boolean
      source?: string
    }>,
    reset: () => ipcRenderer.invoke('patcher:reset') as Promise<{ success: boolean, error?: string }>,
    isOfficial: (url: string) => ipcRenderer.invoke('patcher:isOfficial', url) as Promise<boolean>,
    revokeTrust: (url: string) => ipcRenderer.invoke('patcher:revokeTrust', url) as Promise<{ success: boolean }>,
    getTrustedSources: () => ipcRenderer.invoke('patcher:getTrustedSources') as Promise<string[]>,
    /** 补丁应用完成 */
    onApplied: (callback: (info: { version: string, frontendChanged: boolean, backendChanged: boolean, official: boolean, source: string }) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, info: any) => callback(info)
      ipcRenderer.on('patcher:applied', handler)
      return () => ipcRenderer.removeListener('patcher:applied', handler)
    },
    /** 非官方来源警告 */
    onUnofficialSource: (callback: (info: { url: string, status: string, message: string }) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, info: any) => callback(info)
      ipcRenderer.on('patcher:unofficial-source', handler)
      return () => ipcRenderer.removeListener('patcher:unofficial-source', handler)
    },
    /** 下载进度 */
    onProgress: (callback: (info: { percent: number, file: string }) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, info: any) => callback(info)
      ipcRenderer.on('patcher:progress', handler)
      return () => ipcRenderer.removeListener('patcher:progress', handler)
    },
    /** 错误通知 */
    onError: (callback: (message: string) => void) => {
      const handler = (_event: Electron.IpcRendererEvent, msg: string) => callback(msg)
      ipcRenderer.on('patcher:error', handler)
      return () => ipcRenderer.removeListener('patcher:error', handler)
    },
  },

  // Platform info
  platform: detectPlatform(),
}

contextBridge.exposeInMainWorld('electronAPI', electronAPI)
