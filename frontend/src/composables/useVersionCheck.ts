import { ref } from 'vue'
import API from '@/api/core'
import { CONFIG } from '@/utils/config'

export interface UpdateInfo {
  hasUpdate: boolean
  latestVersion: string
  description: string
  forceUpdate: boolean
  /** null 表示当前平台无可用资源 */
  downloadUrl: string | null
  fileSize: number | null
}

function detectPlatform(): string {
  const p = window.electronAPI?.platform
  if (p === 'darwin')
    return 'macos'
  if (p === 'win32')
    return 'windows'
  if (p === 'linux')
    return 'linux'
  // web 环境做粗略猜测
  const ua = navigator.userAgent.toLowerCase()
  if (ua.includes('mac'))
    return 'macos'
  if (ua.includes('win'))
    return 'windows'
  return 'linux'
}

/** 简易 semver 比较：remote > local 返回 true */
function isNewer(remote: string, local: string): boolean {
  const parse = (v: string) => v.replace(/^v/, '').split('.').map(Number)
  const r = parse(remote)
  const l = parse(local)
  for (let i = 0; i < Math.max(r.length, l.length); i++) {
    const rv = r[i] ?? 0
    const lv = l[i] ?? 0
    if (rv > lv)
      return true
    if (rv < lv)
      return false
  }
  return false
}

export const updateInfo = ref<UpdateInfo | null>(null)
export const showUpdateDialog = ref(false)

export async function checkForUpdate(): Promise<boolean> {
  try {
    const platform = detectPlatform()
    const res = await fetch(`${API.endpoint}/update/latest?platform=${platform}`, {
      signal: AbortSignal.timeout(10_000),
    })

    if (!res.ok)
      return false

    const data = await res.json() as {
      version?: string
      description?: string
      force_update?: boolean
      download_url?: string | null
      file_size?: number | null
      has_update?: boolean
    }

    if (!data.version || data.has_update === false)
      return false

    const currentVersion = CONFIG.value.system.version ?? '5.1.0'
    if (data.version === currentVersion || !isNewer(data.version, currentVersion))
      return false

    updateInfo.value = {
      hasUpdate: true,
      latestVersion: data.version,
      description: data.description ?? '',
      forceUpdate: data.force_update ?? false,
      downloadUrl: data.download_url ?? null,
      fileSize: data.file_size ?? null,
    }
    showUpdateDialog.value = true
    return true
  }
  catch (err) {
    console.warn('[VersionCheck] Failed to check for updates:', err)
    return false
  }
}

export function dismissUpdate(): void {
  showUpdateDialog.value = false
}

export function openDownloadUrl(url: string): void {
  window.open(url, '_blank')
}
