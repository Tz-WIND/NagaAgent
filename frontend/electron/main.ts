import { readdir } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import process from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { app, BrowserWindow, desktopCapturer, ipcMain, Menu, nativeTheme, net, protocol, shell, systemPreferences } from 'electron'
import { startBackend, stopBackend } from './modules/backend'
import { registerHotkeys, unregisterHotkeys } from './modules/hotkeys'
import { createMenu } from './modules/menu'
import { createTray, destroyTray } from './modules/tray'
import { downloadUpdate, installUpdate, setupAutoUpdater } from './modules/updater'
import {
  collapseFloatingWindow,
  collapseFullToCompact,
  createWindow,
  enterFloatingMode,
  exitFloatingMode,
  expandCompactToFull,
  expandFloatingWindow,
  getFloatingState,
  getMainWindow,
  setFloatingHeight,
  setWindowPosition,
} from './modules/window'

let isQuitting = false

// 防止 EPIPE 导致 Electron 崩溃（后端进程 stdout 管道断开时会触发）
process.stdout?.on('error', () => {})
process.stderr?.on('error', () => {})

// Prevent multiple instances
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
}

// ── 自定义协议：naga-char:// 用于加载 characters 目录下的角色资源 ──
// 打包模式：extraResources/characters；开发模式：项目根/characters
const CHARACTERS_DIR = app.isPackaged
  ? resolve(process.resourcesPath, 'characters')
  : resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'characters')
// ── 自定义协议：naga-bg:// 用于加载 premium-assets/backgrounds 目录下的背景图片 ──
const BACKGROUNDS_DIR = app.isPackaged
  ? resolve(process.resourcesPath, 'premium-assets', 'backgrounds')
  : resolve(dirname(fileURLToPath(import.meta.url)), '..', 'premium-assets', 'backgrounds')
protocol.registerSchemesAsPrivileged([
  { scheme: 'naga-char', privileges: { secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } },
  { scheme: 'naga-bg', privileges: { secure: true, supportFetchAPI: true, corsEnabled: true, stream: true } },
  { scheme: 'naga-app', privileges: { secure: true, supportFetchAPI: true, corsEnabled: true, standard: true, stream: true } },
])

app.on('second-instance', () => {
  const win = getMainWindow()
  if (win) {
    if (win.isMinimized())
      win.restore()
    win.show()
    win.focus()
  }
})

app.whenReady().then(async () => {
  // naga-app://路径 → 加载 dist/ 目录文件
  // 仅打包模式生效，开发模式走 Vite dev server
  const appDistDir = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
  protocol.handle('naga-app', (request) => {
    const rawPath = decodeURIComponent(new URL(request.url).pathname).replace(/^\/+/, '')
    const relativePath = rawPath.startsWith('dist/') ? rawPath.slice(5) : rawPath

    const basePath = resolve(appDistDir, relativePath)
    if (!basePath.startsWith(appDistDir)) {
      return new Response('Forbidden', { status: 403 })
    }
    return net.fetch(pathToFileURL(basePath).toString())
  })

  // naga-char://角色名/文件名 → characters/角色名/文件名
  protocol.handle('naga-char', (request) => {
    const relativePath = decodeURIComponent(request.url.slice('naga-char://'.length))
    const filePath = resolve(CHARACTERS_DIR, relativePath)
    if (!filePath.startsWith(CHARACTERS_DIR)) {
      return new Response('Forbidden', { status: 403 })
    }
    return net.fetch(pathToFileURL(filePath).toString())
  })

  // naga-bg://文件名 → premium-assets/backgrounds/文件名
  protocol.handle('naga-bg', (request) => {
    const relativePath = decodeURIComponent(request.url.slice('naga-bg://'.length))
    const filePath = resolve(BACKGROUNDS_DIR, relativePath)
    if (!filePath.startsWith(BACKGROUNDS_DIR)) {
      return new Response('Forbidden', { status: 403 })
    }
    return net.fetch(pathToFileURL(filePath).toString())
  })

  // 强制暗色主题（确保原生菜单等 UI 为深色）
  nativeTheme.themeSource = 'dark'

  // Create menu
  createMenu()

  // Create main window
  const win = createWindow()

  // 透明无边框窗口在 Windows 上 unmaximize 后系统不可靠地还原尺寸，手动保存/还原
  let preMaximizeBounds: Electron.Rectangle | null = null

  // Create system tray
  createTray()

  // Register global hotkeys
  registerHotkeys()

  // Setup auto-updater (checks GitHub Releases for new versions)
  setupAutoUpdater(win)

  // --- IPC Handlers ---

  // Window controls
  ipcMain.on('window:minimize', () => getMainWindow()?.minimize())
  ipcMain.on('window:maximize', () => {
    const w = getMainWindow()
    if (w) {
      if (w.isMaximized()) {
        w.unmaximize()
      }
      else {
        preMaximizeBounds = w.getBounds()
        w.maximize()
      }
    }
  })
  ipcMain.on('window:close', () => {
    const state = getFloatingState()
    if (state === 'compact' || state === 'full') {
      // 悬浮球展开态：收起为球态
      collapseFloatingWindow()
    }
    else if (state === 'classic') {
      // 经典模式：关闭窗口 → 自动进入悬浮球
      enterFloatingMode()
    }
    else {
      // 已经是球态，隐藏到托盘
      getMainWindow()?.hide()
    }
  })

  ipcMain.handle('window:isMaximized', () => getMainWindow()?.isMaximized() ?? false)
  ipcMain.handle('window:getBounds', () => getMainWindow()?.getBounds() ?? { x: 0, y: 0, width: 1280, height: 800 })
  ipcMain.on('window:setBounds', (_event, bounds: { x?: number, y?: number, width?: number, height?: number }) => {
    const win = getMainWindow()
    if (!win || win.isMaximized()) return
    const current = win.getBounds()
    const next = {
      x: bounds.x ?? current.x,
      y: bounds.y ?? current.y,
      width: Math.max(800, bounds.width ?? current.width),
      height: Math.max(600, bounds.height ?? current.height),
    }
    win.setBounds(next)
  })

  // 悬浮球模式控制
  ipcMain.handle('floating:enter', () => {
    enterFloatingMode()
  })
  ipcMain.handle('floating:exit', () => {
    exitFloatingMode()
  })
  ipcMain.handle('floating:expand', (_event, toFull?: boolean) => {
    expandFloatingWindow(toFull ?? false)
  })
  ipcMain.handle('floating:expandToFull', () => {
    expandCompactToFull()
  })
  ipcMain.handle('floating:collapse', () => {
    collapseFloatingWindow()
  })
  ipcMain.handle('floating:collapseToCompact', () => {
    collapseFullToCompact()
  })
  ipcMain.handle('floating:getState', () => getFloatingState())
  ipcMain.on('floating:pin', (_event, pinned: boolean) => {
    const w = getMainWindow()
    if (w) {
      // 固定时显示任务栏图标，取消固定时隐藏（悬浮球模式下 alwaysOnTop 始终为 true）
      w.setSkipTaskbar(!pinned)
    }
  })
  ipcMain.on('floating:setPosition', (_event, x: number, y: number) => {
    setWindowPosition(x, y)
  })
  ipcMain.on('floating:fitHeight', (_event, height: number) => {
    setFloatingHeight(height)
  })

  // Update controls
  ipcMain.on('updater:download', () => downloadUpdate())
  ipcMain.on('updater:install', () => installUpdate())

  // App quit
  ipcMain.on('app:quit', () => {
    isQuitting = true
    app.quit()
  })

  // 悬浮球右键菜单
  ipcMain.on('context-menu:show', () => {
    const menu = Menu.buildFromTemplate([
      {
        label: '打开主界面',
        click: () => exitFloatingMode(),
      },
      {
        label: '隐藏到托盘',
        click: () => getMainWindow()?.hide(),
      },
      { type: 'separator' },
      {
        label: '退出应用',
        click: () => {
          isQuitting = true
          app.quit()
        },
      },
    ])
    menu.popup()
  })

  // 窗口截屏功能
  ipcMain.handle('capture:getSources', async () => {
    // macOS 需要屏幕录制权限
    if (process.platform === 'darwin') {
      const status = systemPreferences.getMediaAccessStatus('screen')
      if (status !== 'granted') {
        return { permission: status }
      }
    }

    try {
      const sources = await desktopCapturer.getSources({
        types: ['window', 'screen'],
        thumbnailSize: { width: 320, height: 180 },
        fetchWindowIcons: true,
      })
      return sources.map(s => ({
        id: s.id,
        name: s.name,
        thumbnail: s.thumbnail.toDataURL(),
        appIcon: s.appIcon?.toDataURL() || null,
      }))
    }
    catch {
      // desktopCapturer 可能因权限问题抛出异常
      return { permission: 'denied' }
    }
  })

  ipcMain.handle('capture:captureWindow', async (_event, sourceId: string) => {
    const sources = await desktopCapturer.getSources({
      types: ['window', 'screen'],
      thumbnailSize: { width: 1920, height: 1080 },
    })
    const target = sources.find(s => s.id === sourceId)
    if (!target)
      return null
    return target.thumbnail.toDataURL()
  })

  // 打开 macOS 屏幕录制权限设置
  ipcMain.handle('capture:openScreenSettings', async () => {
    if (process.platform === 'darwin') {
      await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture')
    }
  })

  // 扫描背景图片文件夹
  ipcMain.handle('backgrounds:scan', async () => {
    try {
      const files = await readdir(BACKGROUNDS_DIR)
      const imageExts = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif']
      return files.filter(f => imageExts.some(ext => f.toLowerCase().endsWith(ext)))
    }
    catch {
      return []
    }
  })

  // 开机自启动
  ipcMain.handle('autoLaunch:get', () => {
    return app.getLoginItemSettings().openAtLogin
  })
  ipcMain.handle('autoLaunch:set', (_event, enabled: boolean) => {
    app.setLoginItemSettings({ openAtLogin: enabled })
  })

  // Minimize to tray on close instead of quitting
  win.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault()
      win.hide()
    }
  })

  win.on('maximize', () => win.webContents.send('window:maximized', true))
  win.on('unmaximize', () => {
    win.webContents.send('window:maximized', false)
    // 透明无边框窗口在 Windows 上还原尺寸不可靠，手动恢复最大化前的 bounds
    if (preMaximizeBounds) {
      win.setBounds(preMaximizeBounds)
      preMaximizeBounds = null
    }
  })

  // 悬浮球展开态失焦时自动收起（由渲染进程控制是否启用）
  win.on('blur', () => {
    win.webContents.send('floating:windowBlur')
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
    else {
      getMainWindow()?.show()
    }
  })

  // Start backend services
  startBackend()
})

app.on('before-quit', () => {
  isQuitting = true
})

app.on('will-quit', () => {
  unregisterHotkeys()
  destroyTray()
  stopBackend()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
