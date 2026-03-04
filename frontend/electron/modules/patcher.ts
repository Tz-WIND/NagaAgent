/**
 * 热补丁系统 - 支持前后端代码增量更新
 *
 * 原理：
 * - 安装目录（resources/）是只读的，存放基线代码
 * - 补丁目录（userData/patches/）是可写的，存放增量更新
 * - 注册 naga-app:// 自定义协议，加载前端文件时优先检查补丁目录
 * - 后端通过 sys.path.insert(0, patch_dir) 优先加载补丁的 .pyc
 *
 * 安全设计（4层）：
 * - L0: HTTPS 通道 + SHA-256 逐文件校验
 * - L1: HMAC-SHA256 manifest 签名验证
 * - L2: 非官方更新源 UI 警告提示
 * - L3: 内嵌官方 URL 白名单，非官方需用户交互确认
 */

import { createHash, createHmac } from 'node:crypto'
import { createReadStream, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { app, dialog, ipcMain, net } from 'electron'
import { getMainWindow } from './window'

// ── 类型定义 ──

export interface PatchFileEntry {
  /** 相对路径，如 "frontend/dist/assets/index-A1b2.js" 或 "backend/apiserver/api_server.pyc" */
  path: string
  /** SHA-256 hex */
  hash: string
  /** 文件大小（字节） */
  size: number
}

export interface PatchManifest {
  /** 补丁版本号，如 "5.1.1-patch.3" */
  version: string
  /** 基线版本要求，如 ">=5.1.0" */
  baseVersion: string
  /** 补丁文件列表 */
  files: PatchFileEntry[]
  /** 服务端签名（HMAC-SHA256 of JSON.stringify(files)），可选 */
  signature?: string
  /** 补丁发布时间 ISO */
  createdAt: string
}

interface LocalManifest {
  version: string
  appliedAt: string
  source: string
  official: boolean
  files: PatchFileEntry[]
}

/** 用户对非官方源的确认记录，避免每次都弹窗 */
interface TrustedSources {
  /** 已确认信任的非官方 URL 列表 */
  urls: string[]
}

// ── L3: 官方更新源白名单 ──
// 只有这些域名/前缀被视为"官方"，其余一律视为第三方
const OFFICIAL_UPDATE_URLS = [
  'https://update.nagaagent.com',
  'https://releases.nagaagent.com',
  'https://api.nagaagent.com',
]

// ── 目录配置 ──

const PATCHES_DIR = join(app.getPath('userData'), 'patches')
const FRONTEND_PATCH_DIR = join(PATCHES_DIR, 'frontend')
const BACKEND_PATCH_DIR = join(PATCHES_DIR, 'backend')
const MANIFEST_PATH = join(PATCHES_DIR, 'manifest.json')
const TRUSTED_SOURCES_PATH = join(PATCHES_DIR, 'trusted_sources.json')

// ── 工具函数 ──

/**
 * 判断 URL 是否属于官方更新源
 */
function isOfficialSource(url: string): boolean {
  return OFFICIAL_UPDATE_URLS.some(official => url.startsWith(official))
}

/**
 * 读取已信任的第三方源列表
 */
function getTrustedSources(): TrustedSources {
  try {
    if (!existsSync(TRUSTED_SOURCES_PATH)) return { urls: [] }
    return JSON.parse(readFileSync(TRUSTED_SOURCES_PATH, 'utf-8')) as TrustedSources
  }
  catch {
    return { urls: [] }
  }
}

/**
 * 保存已信任的第三方源
 */
function saveTrustedSource(url: string): void {
  const trusted = getTrustedSources()
  const normalized = normalizeSourceUrl(url)
  if (!trusted.urls.includes(normalized)) {
    trusted.urls.push(normalized)
    writeFileSync(TRUSTED_SOURCES_PATH, JSON.stringify(trusted, null, 2))
  }
}

/**
 * 标准化 URL 用于信任列表比较（取 origin 部分）
 */
function normalizeSourceUrl(url: string): string {
  try {
    const u = new URL(url)
    return u.origin
  }
  catch {
    return url
  }
}

/**
 * L2+L3: 检查更新源安全性
 * - 官方源：直接通过
 * - 已信任的第三方源：通过，但通知 UI 显示警告标识
 * - 未确认的第三方源：弹窗要求用户确认
 *
 * @returns 'official' | 'trusted' | 'confirmed' | 'rejected'
 */
async function validateUpdateSource(serverUrl: string): Promise<'official' | 'trusted' | 'confirmed' | 'rejected'> {
  // L3: 官方白名单直接放行
  if (isOfficialSource(serverUrl)) {
    return 'official'
  }

  const normalized = normalizeSourceUrl(serverUrl)
  const trusted = getTrustedSources()

  // 已经确认信任过的第三方源
  if (trusted.urls.includes(normalized)) {
    // L2: 虽然放行，但通知渲染进程显示警告标识
    const win = getMainWindow()
    win?.webContents.send('patcher:unofficial-source', {
      url: serverUrl,
      status: 'trusted',
      message: `补丁来源为第三方服务器: ${normalized}`,
    })
    return 'trusted'
  }

  // L3: 未确认的第三方源 → 弹出系统确认对话框
  const win = getMainWindow()
  if (!win) {
    console.warn('[Patcher] 主窗口未就绪，拒绝未确认的第三方源')
    return 'rejected'
  }
  const result = await dialog.showMessageBox(win, {
    type: 'warning',
    title: '非官方更新源',
    message: '检测到第三方补丁服务器',
    detail: [
      `补丁来源: ${normalized}`,
      '',
      '该服务器不在官方白名单中。第三方补丁可能包含未经审核的代码修改。',
      '',
      '如果这是你自己部署的私服或信任的社区服务器，可以选择信任。',
      '否则建议拒绝，以防止恶意代码注入。',
    ].join('\n'),
    buttons: ['拒绝', '仅本次信任', '始终信任此服务器'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  })

  if (result.response === 0) {
    // 拒绝
    console.log(`[Patcher] 用户拒绝了第三方补丁源: ${normalized}`)
    win?.webContents.send('patcher:unofficial-source', {
      url: serverUrl,
      status: 'rejected',
      message: `已拒绝第三方补丁源: ${normalized}`,
    })
    return 'rejected'
  }

  if (result.response === 2) {
    // 始终信任 → 记住
    saveTrustedSource(serverUrl)
    console.log(`[Patcher] 用户已将第三方源加入信任列表: ${normalized}`)
  }

  // L2: 通知渲染进程显示警告
  win?.webContents.send('patcher:unofficial-source', {
    url: serverUrl,
    status: 'trusted',
    message: `补丁来源为第三方服务器: ${normalized}`,
  })

  return 'confirmed'
}

// ── 核心函数 ──

/**
 * 初始化补丁目录结构
 */
export function initPatchDirs(): void {
  for (const dir of [PATCHES_DIR, FRONTEND_PATCH_DIR, BACKEND_PATCH_DIR]) {
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true })
    }
  }
}

/**
 * 读取本地已应用的补丁清单
 */
export function getLocalManifest(): LocalManifest | null {
  try {
    if (!existsSync(MANIFEST_PATH)) return null
    return JSON.parse(readFileSync(MANIFEST_PATH, 'utf-8')) as LocalManifest
  }
  catch {
    return null
  }
}

/**
 * 计算文件 SHA-256
 */
function hashFile(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256')
    const stream = createReadStream(filePath)
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex')))
    stream.on('error', reject)
  })
}

/**
 * 验证 manifest 签名（如果配置了签名密钥）
 */
export function verifyManifestSignature(manifest: PatchManifest, secret?: string): boolean {
  if (!manifest.signature) return true // 未签名，跳过验证（开源场景）
  if (!secret) return false // 有签名但没有密钥，拒绝

  const payload = JSON.stringify(manifest.files)
  const expected = createHmac('sha256', secret).update(payload).digest('hex')
  // 时序安全比较
  if (expected.length !== manifest.signature.length) return false
  let result = 0
  for (let i = 0; i < expected.length; i++) {
    result |= expected.charCodeAt(i) ^ manifest.signature.charCodeAt(i)
  }
  return result === 0
}

/**
 * 检查并下载补丁
 * @param serverUrl 补丁服务器地址，如 "https://update.nagaagent.com"
 * @param currentVersion 当前应用版本
 * @param signSecret 可选的签名验证密钥
 */
export async function checkAndApplyPatches(
  serverUrl: string,
  currentVersion: string,
  signSecret?: string,
): Promise<{ updated: boolean, version?: string, frontendChanged: boolean, backendChanged: boolean, source?: string }> {
  const noUpdate = { updated: false, frontendChanged: false, backendChanged: false }

  if (!serverUrl) return noUpdate

  // ── L2+L3: 更新源安全校验 ──
  const sourceStatus = await validateUpdateSource(serverUrl)
  if (sourceStatus === 'rejected') return noUpdate
  const isOfficial = sourceStatus === 'official'

  const win = getMainWindow()

  try {
    // 1. 获取服务端 manifest
    const manifestUrl = `${serverUrl}/api/patches/manifest?base_version=${currentVersion}`
    const res = await net.fetch(manifestUrl)
    if (!res.ok) return noUpdate

    const remoteManifest = (await res.json()) as PatchManifest

    // 2. 版本比较：如果本地已是最新，跳过
    const local = getLocalManifest()
    if (local && local.version === remoteManifest.version) return noUpdate

    // 3. 签名验证
    if (!verifyManifestSignature(remoteManifest, signSecret)) {
      console.error('[Patcher] 补丁签名验证失败，拒绝应用')
      win?.webContents.send('patcher:error', '补丁签名验证失败')
      return noUpdate
    }

    // 4. 逐文件下载并校验
    let frontendChanged = false
    let backendChanged = false
    const totalFiles = remoteManifest.files.length
    let downloadedFiles = 0

    for (const entry of remoteManifest.files) {
      // 路径安全校验：防止 manifest 中的 "../" 等路径遍历攻击
      const localPath = resolve(PATCHES_DIR, entry.path)
      if (!localPath.startsWith(PATCHES_DIR)) {
        console.error(`[Patcher] 路径越界，已跳过: ${entry.path}`)
        continue
      }
      const dir = join(localPath, '..')
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true })
      }

      // 如果本地已有且 hash 匹配，跳过下载
      if (existsSync(localPath)) {
        const localHash = await hashFile(localPath)
        if (localHash === entry.hash) {
          downloadedFiles++
          continue
        }
      }

      // 下载
      const fileUrl = `${serverUrl}/api/patches/file/${entry.path}`
      const fileRes = await net.fetch(fileUrl)
      if (!fileRes.ok) {
        console.error(`[Patcher] 下载失败: ${entry.path} (${fileRes.status})`)
        continue
      }

      const buffer = Buffer.from(await fileRes.arrayBuffer())

      // SHA-256 校验
      const downloadHash = createHash('sha256').update(buffer).digest('hex')
      if (downloadHash !== entry.hash) {
        console.error(`[Patcher] 文件校验失败: ${entry.path} (期望 ${entry.hash}, 实际 ${downloadHash})`)
        win?.webContents.send('patcher:error', `文件校验失败: ${entry.path}`)
        continue
      }

      writeFileSync(localPath, buffer)
      downloadedFiles++

      // 跟踪哪部分有变化
      if (entry.path.startsWith('frontend/')) frontendChanged = true
      if (entry.path.startsWith('backend/')) backendChanged = true

      // 进度通知
      win?.webContents.send('patcher:progress', {
        percent: Math.round((downloadedFiles / totalFiles) * 100),
        file: entry.path,
      })
    }

    // 5. 保存本地 manifest（含来源信息）
    const localManifest: LocalManifest = {
      version: remoteManifest.version,
      appliedAt: new Date().toISOString(),
      source: normalizeSourceUrl(serverUrl),
      official: isOfficial,
      files: remoteManifest.files,
    }
    writeFileSync(MANIFEST_PATH, JSON.stringify(localManifest, null, 2))

    console.log(`[Patcher] 补丁已应用: ${remoteManifest.version} (${downloadedFiles}/${totalFiles} 文件, 来源: ${isOfficial ? '官方' : '第三方'})`)
    win?.webContents.send('patcher:applied', {
      version: remoteManifest.version,
      frontendChanged,
      backendChanged,
      official: isOfficial,
      source: normalizeSourceUrl(serverUrl),
    })

    return {
      updated: true,
      version: remoteManifest.version,
      frontendChanged,
      backendChanged,
      source: normalizeSourceUrl(serverUrl),
    }
  }
  catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.warn(`[Patcher] 补丁检查失败: ${msg}`)
    return noUpdate
  }
}

/**
 * 解析前端补丁文件路径
 * 给定相对路径（如 "index.html"），返回补丁文件的绝对路径（如果存在）
 */
export function resolveFrontendPatch(relativePath: string): string | null {
  const patchFile = join(FRONTEND_PATCH_DIR, relativePath)
  if (existsSync(patchFile)) {
    return patchFile
  }
  return null
}

/**
 * 获取后端补丁目录路径（供 backend.ts 传递给 Python 进程）
 */
export function getBackendPatchDir(): string {
  return BACKEND_PATCH_DIR
}

/**
 * 检查后端补丁目录是否有内容
 */
export function hasBackendPatches(): boolean {
  try {
    const manifest = getLocalManifest()
    if (!manifest) return false
    return manifest.files.some(f => f.path.startsWith('backend/'))
  }
  catch {
    return false
  }
}

/**
 * 注册补丁相关的 IPC handlers
 */
export function registerPatcherIPC(): void {
  // 查询补丁状态（含来源信息，供 UI 显示警告标识）
  ipcMain.handle('patcher:getStatus', () => {
    const manifest = getLocalManifest()
    return {
      patchVersion: manifest?.version ?? null,
      appliedAt: manifest?.appliedAt ?? null,
      source: manifest?.source ?? null,
      official: manifest?.official ?? true,
      patchDir: PATCHES_DIR,
      fileCount: manifest?.files.length ?? 0,
    }
  })

  // 检查并应用补丁
  ipcMain.handle('patcher:checkUpdate', async (_event, serverUrl: string) => {
    const currentVersion = app.getVersion()
    return await checkAndApplyPatches(serverUrl, currentVersion)
  })

  // 清除所有补丁，回退到基线版本
  ipcMain.handle('patcher:reset', () => {
    try {
      rmSync(PATCHES_DIR, { recursive: true, force: true })
      initPatchDirs()
      return { success: true }
    }
    catch (err) {
      return { success: false, error: String(err) }
    }
  })

  // 查询某个 URL 是否为官方源
  ipcMain.handle('patcher:isOfficial', (_event, url: string) => {
    return isOfficialSource(url)
  })

  // 撤销对某个第三方源的信任
  ipcMain.handle('patcher:revokeTrust', (_event, url: string) => {
    const trusted = getTrustedSources()
    const normalized = normalizeSourceUrl(url)
    trusted.urls = trusted.urls.filter(u => u !== normalized)
    writeFileSync(TRUSTED_SOURCES_PATH, JSON.stringify(trusted, null, 2))
    return { success: true }
  })

  // 获取所有已信任的第三方源
  ipcMain.handle('patcher:getTrustedSources', () => {
    return getTrustedSources().urls
  })
}
