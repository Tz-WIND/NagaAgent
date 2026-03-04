import { ref, watch } from 'vue'
import { ACCESS_TOKEN } from '@/api'
import API from '@/api/core'

const audio = ref<HTMLAudioElement | null>(null)
export const isPlaying = ref(false)
let maxDurationTimer: number | null = null
let abortController: AbortController | null = null

const MAX_PLAYBACK_DURATION = 30000 // 30秒最大播放时长

// ── Progressive TTS Queue ──
const _queue: string[] = []
let _processingQueue = false

/** 移除 markdown 代码块（```...```）和行内代码（`...`），只保留自然语言文本 */
function stripCodeBlocks(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '') // 移除代码块
    .replace(/`[^`]+`/g, '')        // 移除行内代码
    .replace(/\n{3,}/g, '\n\n')     // 压缩多余空行
    .trim()
}

export function speak(text: string): Promise<void> {
  _stopCurrent()

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
    const blob = await res.blob()
    if (blob.size === 0)
      throw new Error('TTS returned empty audio')

    // 如果已被 stop() 中止，不再播放
    if (signal.aborted) return

    const audioBlob = blob.type.startsWith('audio/') ? blob : new Blob([blob], { type: 'audio/mpeg' })
    const objectUrl = URL.createObjectURL(audioBlob)
    const el = new Audio(objectUrl)
    audio.value = el

    // 严格时机：音频真正开始播放时才设 isPlaying=true（驱动 Live2D 张嘴）
    el.onplay = () => {
      isPlaying.value = true
    }

    el.onended = () => {
      cleanup(objectUrl)
    }

    el.onerror = () => {
      cleanup(objectUrl)
    }

    // 设置30秒最大播放时长定时器（仅跳过当前句，不清空队列）
    maxDurationTimer = window.setTimeout(() => {
      if (audio.value) {
        _stopCurrent()
      }
    }, MAX_PLAYBACK_DURATION)

    el.play()
  }).catch((err) => {
    // AbortError 是正常取消，不需要报错
    if (err instanceof DOMException && err.name === 'AbortError') return
    cleanup()
    console.error('[TTS] speak failed:', err)
    throw err
  })
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

/** 停止当前播放（不清理队列，内部使用） */
function _stopCurrent() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  if (maxDurationTimer) {
    clearTimeout(maxDurationTimer)
    maxDurationTimer = null
  }
  if (audio.value) {
    audio.value.pause()
    audio.value = null
  }
  isPlaying.value = false
}

/** 停止所有 TTS（当前播放 + 清空队列） */
export function stop() {
  _queue.length = 0
  _processingQueue = false
  _stopCurrent()
}

/** 逐句入队，按顺序播放（流式 TTS 用） */
export function queueSpeak(text: string): void {
  const clean = stripCodeBlocks(text).trim()
  if (!clean) return
  _queue.push(clean)
  if (!_processingQueue) _drainQueue()
}

/** 清空待播放队列（不中断当前播放） */
export function clearSpeakQueue(): void {
  _queue.length = 0
}

async function _drainQueue(): Promise<void> {
  if (_queue.length === 0) { _processingQueue = false; return }
  _processingQueue = true
  const text = _queue.shift()!
  try {
    await speak(text)
    // 等待当前音频播放完毕
    if (isPlaying.value) {
      await new Promise<void>((resolve) => {
        const unwatch = watch(isPlaying, (val) => {
          if (!val) { unwatch(); resolve() }
        })
        setTimeout(() => { unwatch(); resolve() }, 35000)
      })
    }
  }
  catch { /* 当前句失败，继续下一句 */ }
  _drainQueue()
}
