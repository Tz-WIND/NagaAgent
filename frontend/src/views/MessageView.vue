<script lang="ts">
import { onKeyStroke, useEventListener } from '@vueuse/core'
import { nextTick, onMounted, ref, useTemplateRef, watch } from 'vue'
import { ACCESS_TOKEN, authExpired } from '@/api'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import MessageItem from '@/components/MessageItem.vue'
import { toolMessage } from '@/composables/useToolStatus'
import { CONFIG } from '@/utils/config'
import { live2dState, setEmotion } from '@/utils/live2dController'
import { CURRENT_SESSION_ID, formatRelativeTime, IS_TEMPORARY_SESSION, loadCurrentSession, MESSAGES, newSession, switchSession } from '@/utils/session'
import { clearSpeakQueue, isPlaying, queueSpeak, stop as stopTTS } from '@/utils/tts'

const isSending = ref(false)
const messageQueue: Array<{ content: string, options?: any }> = []
const ttsEnabled = ref(localStorage.getItem('ttsEnabled') !== 'false')

async function processQueue() {
  if (messageQueue.length === 0 || isSending.value) return

  const { content, options } = messageQueue.shift()!
  await chatStreamInternal(content, options)
}

export function chatStream(content: string, options?: { skill?: string, images?: string[], voiceInput?: boolean }) {
  // 用户发送新消息时，立即中止上一次的 TTS 播放
  stopTTS()

  // 立即显示用户消息
  MESSAGES.value.push({ role: 'user', content: options?.images?.length ? `[截图x${options.images.length}] ${content}` : content })

  // 将消息加入队列
  messageQueue.push({ content, options })
  processQueue()
}

async function chatStreamInternal(content: string, options?: { skill?: string, images?: string[], voiceInput?: boolean }) {
  isSending.value = true

  // 预先推入 assistant 消息（立即显示，不等 API 响应）
  MESSAGES.value.push({ role: 'assistant', content: '', reasoning: '', generating: true, status: options?.voiceInput ? '理解话语中' : undefined })
  const message = MESSAGES.value[MESSAGES.value.length - 1]!
  // 追踪纯LLM内容（不含工具状态标记），用于TTS朗读
  let spokenContent = ''

  // 语音模式：开启时在流式输出中逐句送入 TTS 队列（文本始终实时显示）
  const voiceSync = CONFIG.value.system.voice_enabled
  let contentBuf = ''
  const pushContent = (text: string) => {
    contentBuf += text
    message.content = contentBuf
  }

  live2dState.value = 'thinking'
  let compressTimer: ReturnType<typeof setTimeout> | undefined
  // 逐句 TTS：在流式输出中检测句子边界，逐句送入 TTS 队列
  let ttsSentenceBuf = ''

  // 记录当前轮次 content 流的起始位置，content_clean 只替换当前轮的 LLM 输出
  let roundContentStart = 0

  API.chatStream(content, {
    sessionId: CURRENT_SESSION_ID.value ?? undefined,
    disableTTS: true,
    skill: options?.skill,
    images: options?.images,
    temporary: IS_TEMPORARY_SESSION.value || undefined,
  }).then(async ({ sessionId, response }) => {
    if (sessionId) {
      CURRENT_SESSION_ID.value = sessionId
    }

    // 情感解析函数
    function parseEmotionFromText(text: string): 'normal' | 'positive' | 'negative' | 'surprise' {
      if (text.includes('【正面情感】')) {
        return 'positive'
      }
      else if (text.includes('【负面情感】')) {
        return 'negative'
      }
      else if (text.includes('【惊讶情感】')) {
        return 'surprise'
      }
      return 'normal'
    }

    for await (const chunk of response) {
      if (chunk.type === 'reasoning') {
        message.reasoning = (message.reasoning || '') + chunk.text
      }
      else if (chunk.type === 'content') {
        pushContent(chunk.text || '')
        spokenContent += chunk.text
        // 检测情感标记并设置表情
        const emotion = parseEmotionFromText(chunk.text || '')
        if (emotion !== 'normal') {
          void setEmotion(emotion)
        }
        // 逐句 TTS：检测句子边界（。！？）并入队
        if (voiceSync) {
          ttsSentenceBuf += chunk.text || ''
          const parts = ttsSentenceBuf.split(/(?<=[。！？])/)
          if (parts.length > 1) {
            for (let i = 0; i < parts.length - 1; i++) {
              const s = parts[i]!.trim()
              if (s && ttsEnabled.value)
                queueSpeak(s)
            }
            ttsSentenceBuf = parts[parts.length - 1]!
          }
        }
      }
      else if (chunk.type === 'content_clean') {
        // 仅替换当前轮次的 LLM 输出（从 roundContentStart 开始），保留之前轮次的工具通知
        contentBuf = contentBuf.substring(0, roundContentStart) + (chunk.text || '')
        message.content = contentBuf
        spokenContent = chunk.text || ''
        // 内容被替换，清空待播放队列并重置句子缓冲
        if (voiceSync) {
          clearSpeakQueue()
          ttsSentenceBuf = ''
        }
      }
      else if (chunk.type === 'tool_calls') {
        // 显示工具调用状态
        const calls = chunk.calls || []
        const callDesc = calls.map((c: any) => {
          const name = c.service_name || c.agentType || 'tool'
          return `🔧 ${name}`
        }).join(', ')
        pushContent(`\n\n> 正在执行工具: ${callDesc}...\n`)
        // OpenClaw 工具可能耗时较长，添加提示
        const hasOpenclaw = calls.some((c: any) => {
          const name = (c.service_name || c.agentType || '').toLowerCase()
          return name.includes('openclaw') || name.includes('agent')
        })
        if (hasOpenclaw) {
          pushContent('> ⏳ OpenClaw 工具处理可能会比较久，预计需要两分钟\n')
        }
      }
      else if (chunk.type === 'tool_results') {
        // 显示工具结果摘要
        const results = chunk.results || []
        for (const r of results) {
          const status = r.status === 'success' ? '✅' : '❌'
          const label = r.tool_name ? `${r.service_name}: ${r.tool_name}` : r.service_name
          pushContent(`\n> ${status} ${label}\n`)
        }
        pushContent('\n')
        // 工具结果追加完毕，更新下一轮 content 的起始位置
        roundContentStart = contentBuf.length
      }
      else if (chunk.type === 'round_start' && (chunk.round ?? 0) > 1) {
        // 多轮分隔
        pushContent('\n---\n\n')
        // 新一轮开始，更新 content 起始位置
        roundContentStart = contentBuf.length
      }
      else if (chunk.type === 'token_refreshed') {
        // 后端刷新了 token，同步到前端（防止后续轮询请求用旧 token 覆盖）
        if (chunk.text) {
          ACCESS_TOKEN.value = chunk.text
        }
      }
      else if (chunk.type === 'auth_expired') {
        // 后端 LLM 认证失败且刷新也失败，触发重新登录
        authExpired.value = true
        pushContent(chunk.text || '登录已过期，请重新登录')
      }
      else if (chunk.type === 'status') {
        message.status = chunk.text || ''
      }
      else if (chunk.type === 'intent_result') {
        const tools = (chunk as any).tools || []
        if (tools.length > 0) {
          message.status = `调度: ${tools.join(', ')}`
        }
      }
      else if (chunk.type === 'pre_search_start') {
        message.status = `搜索: ${chunk.text || ''}`
      }
      else if (chunk.type === 'pre_search_end') {
        message.status = chunk.text || '搜索完成'
      }
      else if (chunk.type === 'compress_start' || chunk.type === 'compress_progress' || chunk.type === 'compress_end') {
        // 上下文压缩进度提示（覆盖式显示，直接写 message.content 不走缓冲）
        message.content = `> ${chunk.text}\n\n`
        if (chunk.type === 'compress_end') {
          compressTimer = setTimeout(() => {
            message.content = ''
          }, 1200)
        }
      }
      else if (chunk.type === 'compress_info') {
        // 运行时压缩完成，在当前 assistant 消息前插入 info 标记
        if (compressTimer) {
          clearTimeout(compressTimer)
          compressTimer = undefined
        }
        message.content = ''
        const idx = MESSAGES.value.indexOf(message)
        if (idx > 0) {
          MESSAGES.value.splice(idx, 0, { role: 'info', content: chunk.text || '【已压缩上下文】' })
        }
      }
      // round_end 不需要特殊处理
      window.dispatchEvent(new CustomEvent('token', { detail: chunk.text || '' }))
    }

    // 清理生成状态（文本已实时显示，无需等待 TTS）
    delete message.generating
    delete message.status
    if (!message.reasoning)
      delete message.reasoning

    if (voiceSync && spokenContent) {
      // 将剩余未成句的文本送入 TTS 队列
      if (ttsSentenceBuf.trim() && ttsEnabled.value)
        queueSpeak(ttsSentenceBuf.trim())
      // Live2D 状态由 isPlaying watcher 自动驱动: talking ↔ idle
    }
    if (!isPlaying.value) {
      live2dState.value = 'idle'
    }
  }).catch((err) => {
    live2dState.value = 'idle'
    message.content = `Error: ${err.message}`
    delete message.generating
    delete message.status
    if (message.reasoning === '')
      delete message.reasoning
  }).finally(() => {
    isSending.value = false
    processQueue()
  })
}
</script>

<script setup lang="ts">
const input = defineModel<string>()
const containerRef = useTemplateRef('containerRef')
const fileInput = ref<HTMLInputElement | null>(null)

function toggleTTS() {
  ttsEnabled.value = !ttsEnabled.value
  localStorage.setItem('ttsEnabled', String(ttsEnabled.value))
  if (!ttsEnabled.value) {
    stopTTS() // 关闭时停止当前播放
  }
}

// TTS 播放状态驱动嘴部动画：开始播放→talking，结束→idle
watch(isPlaying, (playing) => {
  live2dState.value = playing ? 'talking' : 'idle'
})

function scrollToBottom() {
  containerRef.value?.scrollToBottom()
}

function sendMessage() {
  if (input.value) {
    chatStream(input.value)
    nextTick().then(scrollToBottom)
    input.value = ''
  }
}

onMounted(() => {
  loadCurrentSession()
  scrollToBottom()
})
useEventListener('token', scrollToBottom)
onKeyStroke('Enter', (e) => {
  if (e.isComposing)
    return
  sendMessage()
})

// Session history
const showHistory = ref(false)
const sessions = ref<Array<{
  sessionId: string
  createdAt: string
  lastActiveAt: string
  conversationRounds: number
  temporary: boolean
}>>([])
const loadingSessions = ref(false)

async function fetchSessions() {
  loadingSessions.value = true
  try {
    const res = await API.getSessions()
    sessions.value = res.sessions ?? []
  }
  catch {
    sessions.value = []
  }
  loadingSessions.value = false
}

function toggleHistory() {
  showHistory.value = !showHistory.value
  if (showHistory.value) {
    fetchSessions()
  }
}

async function handleSwitchSession(id: string) {
  await switchSession(id)
  showHistory.value = false
  nextTick().then(scrollToBottom)
}

async function handleDeleteSession(id: string) {
  try {
    await API.deleteSession(id)
    sessions.value = sessions.value.filter(s => s.sessionId !== id)
    if (CURRENT_SESSION_ID.value === id) {
      newSession()
    }
  }
  catch { /* ignore */ }
}

function handleNewSession() {
  newSession()
  showHistory.value = false
}

function triggerUpload() {
  fileInput.value?.click()
}

async function handleFileUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file)
    return

  const ext = file.name.split('.').pop()?.toLowerCase()
  const parseable = ['docx', 'xlsx', 'txt', 'csv', 'md']

  if (ext && parseable.includes(ext)) {
    // 解析文档内容后发送给文本模型
    MESSAGES.value.push({ role: 'system', content: `正在解析文件: ${file.name}...` })
    try {
      const result = await API.parseDocument(file)
      const msg = MESSAGES.value[MESSAGES.value.length - 1]!
      const truncNote = result.truncated ? '（内容过长，已截断）' : ''
      msg.content = `文件解析完成: ${file.name}${truncNote}`
      chatStream(`以下是文件「${file.name}」的内容：\n\n${result.content}\n\n请分析这个文件的内容。`)
      nextTick().then(scrollToBottom)
    }
    catch (err: any) {
      const msg = MESSAGES.value[MESSAGES.value.length - 1]!
      msg.content = `文件解析失败: ${err?.response?.data?.detail || err.message}`
    }
  }
  else {
    // 其他格式走原有上传逻辑
    MESSAGES.value.push({ role: 'system', content: `正在上传文件: ${file.name}...` })
    try {
      const result = await API.uploadDocument(file)
      const msg = MESSAGES.value[MESSAGES.value.length - 1]!
      msg.content = `文件上传成功: ${file.name}`
      if (result.filePath) {
        chatStream(`请分析我刚上传的文件「${file.name}」，文件完整路径: ${result.filePath}`)
      }
    }
    catch (err: any) {
      const msg = MESSAGES.value[MESSAGES.value.length - 1]!
      msg.content = `文件上传失败: ${err.message}`
    }
  }
  target.value = ''
}

// ── 语音输入（MediaRecorder + ASR API） ──
const isRecording = ref(false)
let mediaRecorder: MediaRecorder | null = null
let audioChunks: Blob[] = []

async function toggleVoiceInput() {
  if (!CONFIG.value.voice_realtime.enabled)
    return

  if (isRecording.value) {
    stopVoiceInput()
    return
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    audioChunks = []
    mediaRecorder = new MediaRecorder(stream, { mimeType: getSupportedMimeType() })

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0)
        audioChunks.push(e.data)
    }

    mediaRecorder.onstop = async () => {
      // 停止所有音轨，释放麦克风
      stream.getTracks().forEach(t => t.stop())
      if (audioChunks.length === 0)
        return

      const audioBlob = new Blob(audioChunks, { type: mediaRecorder?.mimeType || 'audio/webm' })
      try {
        const { text } = await API.transcribeAudio(audioBlob, { language: 'zh' })
        if (text && typeof text === 'string' && text.trim()) {
          // 语音识别成功：直接发送（带语音标注前缀）
          chatStream(`以下是用户的语音输入：【${text.trim()}】`, { voiceInput: true })
          nextTick().then(scrollToBottom)
        }
      }
      catch (err: any) {
        const status = err?.response?.status
        if (status === 401) {
          MESSAGES.value.push({ role: 'system', content: '语音识别需要登录后使用' })
        }
        else if (status === 402) {
          MESSAGES.value.push({ role: 'system', content: '余额不足，无法使用语音识别' })
        }
        else {
          MESSAGES.value.push({ role: 'system', content: `语音识别失败: ${err.message || err}` })
        }
      }
    }

    mediaRecorder.start()
    isRecording.value = true
  }
  catch (err: any) {
    if (err.name === 'NotAllowedError') {
      MESSAGES.value.push({ role: 'system', content: '麦克风权限被拒绝，请在系统设置中允许麦克风访问' })
    }
    else {
      MESSAGES.value.push({ role: 'system', content: `无法启动录音: ${err.message || err}` })
    }
  }
}

function stopVoiceInput() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  mediaRecorder = null
  isRecording.value = false
}

function getSupportedMimeType(): string {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  for (const t of types) {
    if (MediaRecorder.isTypeSupported(t))
      return t
  }
  return ''
}
</script>

<template>
  <div class="flex flex-col gap-8 relative">
    <BoxContainer ref="containerRef" class="w-full grow">
      <div class="grid gap-4 pb-8">
        <MessageItem
          v-for="item, index in MESSAGES" :key="index"
          :role="item.role" :content="item.content"
          :reasoning="item.reasoning" :sender="item.sender"
          :generating="item.generating" :status="item.status"
          :class="(item.generating && index === MESSAGES.length - 1) || 'border-b'"
        />
      </div>
    </BoxContainer>

    <!-- Session History Panel -->
    <Transition name="slide-up">
      <div v-if="showHistory" class="session-panel">
        <div class="flex items-center justify-between px-3 py-2 border-b border-white/10">
          <span class="text-white/70 text-sm font-bold">对话历史</span>
          <button
            class="text-white/40 hover:text-white/80 bg-transparent border-none cursor-pointer text-xs"
            @click="showHistory = false"
          >
            关闭
          </button>
        </div>
        <div class="overflow-y-auto max-h-48">
          <div v-if="loadingSessions" class="text-white/40 text-xs text-center py-4">
            加载中...
          </div>
          <div v-else-if="sessions.length === 0" class="text-white/40 text-xs text-center py-4">
            暂无历史对话
          </div>
          <div
            v-for="s in sessions" :key="s.sessionId"
            class="session-item"
            :class="{ 'bg-white/10': s.sessionId === CURRENT_SESSION_ID }"
            @click="handleSwitchSession(s.sessionId)"
          >
            <div class="flex-1 min-w-0">
              <div class="text-white/80 text-sm truncate">
                {{ s.sessionId.slice(0, 8) }}...
              </div>
              <div class="text-white/40 text-xs">
                {{ formatRelativeTime(s.lastActiveAt) }} · {{ s.conversationRounds }} 轮对话
              </div>
            </div>
            <button
              class="text-white/30 hover:text-red-400 bg-transparent border-none cursor-pointer text-xs shrink-0 ml-2"
              title="删除"
              @click.stop="handleDeleteSession(s.sessionId)"
            >
              x
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <div v-if="toolMessage" class="mx-[var(--nav-back-width)] text-white/50 text-xs px-2 py-1">
      {{ toolMessage }}
    </div>
    <div class="mx-[var(--nav-back-width)]">
      <div class="box flex items-center gap-2">
        <button
          class="p-2 text-white/60 hover:text-white bg-transparent border-none cursor-pointer text-sm shrink-0"
          title="新建对话"
          @click="handleNewSession"
        >
          +
        </button>
        <button
          class="p-2 text-white/60 hover:text-white bg-transparent border-none cursor-pointer text-sm shrink-0"
          :class="{ 'text-white!': showHistory }"
          title="对话历史"
          @click="toggleHistory"
        >
          H
        </button>
        <input
          v-model="input"
          class="p-2 lh-none text-white w-full bg-transparent border-none outline-none"
          type="text"
          placeholder="Type a message..."
        >
        <button
          v-if="CONFIG.voice_realtime.enabled"
          class="input-icon-btn shrink-0"
          :class="{ recording: isRecording }"
          :title="isRecording ? '停止录音' : '语音输入'"
          @click="toggleVoiceInput"
        >
          <svg v-if="!isRecording" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" x2="12" y1="19" y2="22" /></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
        </button>
        <button
          v-if="CONFIG.system.voice_enabled"
          class="input-icon-btn shrink-0"
          :title="ttsEnabled ? '关闭语音播报' : '开启语音播报'"
          @click="toggleTTS"
        >
          <svg v-if="ttsEnabled" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /></svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><line x1="22" y1="9" x2="16" y2="15" /><line x1="16" y1="9" x2="22" y2="15" /></svg>
        </button>
        <button
          class="input-icon-btn shrink-0"
          title="上传文件 (Word/Excel/文本)"
          @click="triggerUpload"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M12 18v-6" /><path d="m9 15 3-3 3 3" /></svg>
        </button>
        <input
          ref="fileInput"
          type="file"
          accept=".docx,.xlsx,.txt,.csv,.md,.pdf,.png,.jpg,.jpeg"
          class="hidden"
          @change="handleFileUpload"
        >
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-panel {
  position: absolute;
  left: var(--nav-back-width);
  right: 0;
  bottom: 5rem;
  background: rgba(30, 30, 30, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  backdrop-filter: blur(12px);
  z-index: 10;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: all 0.2s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

.input-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: color 0.2s, background 0.2s;
}

.input-icon-btn:hover {
  color: rgba(255, 255, 255, 0.9);
  background: rgba(255, 255, 255, 0.08);
}

.input-icon-btn.recording {
  color: #e85d5d;
  animation: recording-pulse 1.2s ease-in-out infinite;
}

@keyframes recording-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
