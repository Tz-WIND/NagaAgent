import { join } from 'node:path'
import process from 'node:process'
import { app, Menu, nativeImage, Tray } from 'electron'
import { getMainWindow } from './window'

let tray: Tray | null = null

export function createTray(): Tray {
  // In dev: icon is at project_root/build/icon.png
  // In production: icon is at resources/build/icon.png
  const iconPath = app.isPackaged
    ? join(process.resourcesPath, 'build', 'icon.png')
    : join(app.getAppPath(), 'build', 'icon.png')
  let icon: Electron.NativeImage
  try {
    // 980x980 直接缩到 16x16 会导致 Windows 托盘只显示顶部（帽子）。
    // 先缩到 64x64 中间尺寸再缩到目标尺寸，避免极端缩放比导致裁切/失真。
    // macOS 托盘推荐 22x22（Retina 自动 2x），Windows 推荐 16x16。
    const isWin = process.platform === 'win32'
    const traySize = isWin ? 16 : 22
    icon = nativeImage.createFromPath(iconPath)
      .resize({ width: 64, height: 64 })
      .resize({ width: traySize, height: traySize })
  }
  catch {
    icon = nativeImage.createEmpty()
  }

  tray = new Tray(icon)
  tray.setToolTip('Naga Agent')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => {
        const win = getMainWindow()
        if (win) {
          win.show()
          win.focus()
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)

  // Click tray icon to show window
  tray.on('click', () => {
    const win = getMainWindow()
    if (win) {
      if (win.isVisible()) {
        win.focus()
      }
      else {
        win.show()
      }
    }
  })

  return tray
}

export function destroyTray(): void {
  if (tray) {
    tray.destroy()
    tray = null
  }
}
