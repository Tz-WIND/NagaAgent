import { ref } from 'vue'
import { ACCESS_TOKEN } from '@/api'
import API from '@/api/core'

const audio = ref<HTMLAudioElement | null>(null)
export const isPlaying = ref(false)
let maxDurationTimer: number | null = null
let abortController: AbortController | null = null

const MAX_PLAYBACK_DURATION = 30000 // 30秒最大播放时长

/** 移除 markdown 代码块（```...```）和行内代码（`...`），只保留自然语言文本 */
function stripCodeBlocks(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '') // 移除代码块
    .replace(/`[^`]+`/g, '')        // 移除行内代码
    .replace(/\n{3,}/g, '\n\n')     // 压缩多余空行
    .trim()
}

export function speak(text: string): Promise<void> {
  stop()

  // 移除代码块，只朗读自然语言
  const cleanText = stripCodeBlocks(text)
  if (!cleanText) return Promise.resolve()

  // 走 API Server 代理（和 chatStream 同一个 endpoint），后端自动判断走 NagaBusiness 还是本地 edge-tts
  const url = `${API.endpoint}/tts/speech`

  const isLoggedIn = !!ACCESS_TOKEN.value
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (isLoggedIn) {
    headers.Authorization = `Bearer ${ACCESS_TOKEN.value}`
  }

  // 创建 AbortController 以便中途取消 fetch
  abortController = new AbortController()
  const { signal } = abortController

  return fetch(url, {
    method: 'POST',
    headers,
    signal,
    body: JSON.stringify({
      model: isLoggedIn ? 'default' : 'tts-1',
      input: cleanText,
      voice: isLoggedIn ? 'Cherry' : 'zh-CN-XiaoyiNeural',
      speed: 1.0,
      response_format: 'mp3',
    }),
  }).then(async (res) => {
    if (!res.ok)
      throw new Error(`TTS responded ${res.status}`)

    // 如果已被 stop() 中止，不再播放
    if (signal.aborted) return

    // ★ 流式播放：用 MediaSource 边收边播，大幅减少首音延迟
    if (typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg')) {
      await _streamPlayback(res, signal)
    } else {
      // 降级：不支持 MediaSource 的浏览器走原始 blob 方式
      await _blobPlayback(res, signal)
    }
  }).catch((err) => {
    // AbortError 是正常取消，不需要报错
    if (err instanceof DOMException && err.name === 'AbortError') return
    cleanup()
    console.error('[TTS] speak failed:', err)
    throw err
  })
}

/** 流式播放——边接收边播放，首音延迟降至 <500ms */
async function _streamPlayback(res: Response, signal: AbortSignal): Promise<void> {
  const mediaSource = new MediaSource()
  const objectUrl = URL.createObjectURL(mediaSource)
  const el = new Audio(objectUrl)
  audio.value = el

  el.onplay = () => { isPlaying.value = true }
  el.onended = () => { cleanup(objectUrl) }
  el.onerror = () => { cleanup(objectUrl) }

  // 设置30秒最大播放时长定时器
  maxDurationTimer = window.setTimeout(() => {
    if (audio.value) stop()
  }, MAX_PLAYBACK_DURATION)

  return new Promise<void>((resolve, reject) => {
    mediaSource.addEventListener('sourceopen', async () => {
      const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg')
      const reader = res.body?.getReader()
      if (!reader) {
        cleanup(objectUrl)
        reject(new Error('No response body'))
        return
      }

      let firstChunk = true
      try {
        while (true) {
          if (signal.aborted) { reader.cancel(); break }
          const { done, value } = await reader.read()
          if (done) break
          if (!value || value.length === 0) continue

          // 等待 sourceBuffer 可写
          if (sourceBuffer.updating) {
            await new Promise<void>(r => sourceBuffer.addEventListener('updateend', () => r(), { once: true }))
          }
          sourceBuffer.appendBuffer(value)
          await new Promise<void>(r => sourceBuffer.addEventListener('updateend', () => r(), { once: true }))

          // 收到第一块数据后立即开始播放
          if (firstChunk) {
            firstChunk = false
            el.play().catch(() => {})
          }
        }
      } catch (e: any) {
        if (e?.name === 'AbortError' || signal.aborted) { /* 正常取消 */ }
        else { console.warn('[TTS] stream error:', e) }
      }

      // 流结束，关闭 MediaSource
      try {
        if (mediaSource.readyState === 'open') {
          if (sourceBuffer.updating) {
            await new Promise<void>(r => sourceBuffer.addEventListener('updateend', () => r(), { once: true }))
          }
          mediaSource.endOfStream()
        }
      } catch { /* ignore */ }
      resolve()
    }, { once: true })
  })
}

/** 降级播放——完整下载后播放（老浏览器兜底） */
async function _blobPlayback(res: Response, signal: AbortSignal): Promise<void> {
  const blob = await res.blob()
  if (blob.size === 0) throw new Error('TTS returned empty audio')
  if (signal.aborted) return

  const audioBlob = blob.type.startsWith('audio/') ? blob : new Blob([blob], { type: 'audio/mpeg' })
  const objectUrl = URL.createObjectURL(audioBlob)
  const el = new Audio(objectUrl)
  audio.value = el

  el.onplay = () => { isPlaying.value = true }
  el.onended = () => { cleanup(objectUrl) }
  el.onerror = () => { cleanup(objectUrl) }

  maxDurationTimer = window.setTimeout(() => {
    if (audio.value) stop()
  }, MAX_PLAYBACK_DURATION)

  el.play()
}

function cleanup(objectUrl?: string) {
  if (maxDurationTimer) {
    clearTimeout(maxDurationTimer)
    maxDurationTimer = null
  }
  isPlaying.value = false
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
  }
  audio.value = null
}

export function stop() {
  // 取消正在进行的 fetch 请求
  if (abortController) {
    abortController.abort()
    abortController = null
  }

  // 清除定时器
  if (maxDurationTimer) {
    clearTimeout(maxDurationTimer)
    maxDurationTimer = null
  }

  if (audio.value) {
    audio.value.pause()
    audio.value = null
  }
  // 立即闭嘴
  isPlaying.value = false
}
