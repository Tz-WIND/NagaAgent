import type { StreamChunk } from '@/utils/encoding'
import { useStorage } from '@vueuse/core'
import { ref } from 'vue'
import API from '@/api/core'

export interface Message {
  role: 'system' | 'user' | 'assistant' | 'info'
  content: string
  reasoning?: string
  generating?: boolean
  status?: string
  sender?: string
}

// ── Tab 状态管理 ──

export interface ChatTab {
  id: string // 'naga' 或 uuid
  type: 'naga' | 'agent'
  name: string // '娜迦' | '干员1' | 自定义名
  instanceId?: string // 后端实例 ID（仅 agent tab）
  messages: Message[]
  unread: number
}

/** 所有 tab，第一个固定为娜迦 */
export const tabs = ref<ChatTab[]>([
  { id: 'naga', type: 'naga', name: '娜迦', messages: [], unread: 0 },
])

/** 当前活跃 tab（持久化到 localStorage） */
export const activeTabId = useStorage('naga-active-tab', 'naga')

/** 干员编号计数器（只增不减，不复用编号，避免混淆） */
let agentCounter = 0
export function nextAgentNumber(): number {
  return ++agentCounter
}

export function getActiveTab(): ChatTab {
  return tabs.value.find(t => t.id === activeTabId.value) || tabs.value[0]
}

export function getNagaTab(): ChatTab {
  return tabs.value[0]
}

// ── 通讯录状态 ──

export interface AgentContact {
  id: string
  name: string
  running: boolean
  created_at: number
}

/** 通讯录列表（从后端 GET /openclaw/agents 加载） */
export const agentContacts = ref<AgentContact[]>([])

/** 加载通讯录 */
export async function loadAgentContacts() {
  try {
    const res = await API.listAgents()
    agentContacts.value = res.agents || []

    // 更新 counter 避免编号冲突
    const maxNum = agentContacts.value.reduce((max, a) => {
      const m = a.name.match(/^干员(\d+)$/)
      return m ? Math.max(max, parseInt(m[1])) : max
    }, 0)
    if (maxNum > agentCounter) agentCounter = maxNum
  } catch {
    // 后端未就绪
  }
}

/** 从通讯录打开干员 tab（如果 tab 已存在则切换，否则创建并立即加载历史） */
export function openAgentTab(contact: AgentContact) {
  const existing = tabs.value.find(t => t.instanceId === contact.id)
  if (existing) {
    activeTabId.value = existing.id
    return existing
  }

  const tab: ChatTab = {
    id: `agent-${contact.id}`,
    type: 'agent',
    name: contact.name,
    instanceId: contact.id,
    messages: [],
    unread: 0,
  }
  tabs.value.push(tab)
  activeTabId.value = tab.id

  // 立即触发加载（同步设置 loading 状态，避免首帧闪烁）
  loadAgentMessages(tab)

  return tab
}

// ── 娜迦 tab 的 MESSAGES 保持兼容 ──

export const CURRENT_SESSION_ID = useStorage<string | null>('naga-session', null)
export const MESSAGES = ref<Message[]>([])
export const IS_TEMPORARY_SESSION = ref(false)

// 娜迦 tab 的 messages 与 MESSAGES.value 保持同一引用
tabs.value[0].messages = MESSAGES.value

function syncNagaMessages() {
  tabs.value[0].messages = MESSAGES.value
}

export async function loadCurrentSession() {
  if (CURRENT_SESSION_ID.value) {
    try {
      const detail = await API.getSessionDetail(CURRENT_SESSION_ID.value)
      MESSAGES.value = detail.messages.map(m => ({
        role: m.role as Message['role'],
        content: m.content,
      }))
      syncNagaMessages()
      return
    }
    catch {
      CURRENT_SESSION_ID.value = null
    }
  }
  MESSAGES.value = []
  syncNagaMessages()
}

export function newSession() {
  CURRENT_SESSION_ID.value = null
  MESSAGES.value = []
  syncNagaMessages()
  IS_TEMPORARY_SESSION.value = false
}

export function newTemporarySession() {
  CURRENT_SESSION_ID.value = null
  MESSAGES.value = []
  syncNagaMessages()
  IS_TEMPORARY_SESSION.value = true
}

export async function switchSession(id: string) {
  CURRENT_SESSION_ID.value = id
  IS_TEMPORARY_SESSION.value = false
  await loadCurrentSession()
}

export function formatRelativeTime(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1)
    return '刚刚'
  if (diffMin < 60)
    return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24)
    return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7)
    return `${diffDay}天前`
  return d.toLocaleDateString()
}

/**
 * 懒加载干员 tab 的对话历史（从 OpenClaw session 恢复）。
 * 后端会自动 ensure_running 启动进程（可能需要数秒）。
 */
const _loadingAgents = ref(new Set<string>())

export function isAgentLoading(instanceId: string) {
  return _loadingAgents.value.has(instanceId)
}

export async function loadAgentMessages(tab: ChatTab) {
  if (!tab.instanceId) return
  if (_loadingAgents.value.has(tab.instanceId)) return
  // 跳过已有真实消息的 tab
  if (tab.messages.length > 0) return
  _loadingAgents.value = new Set([..._loadingAgents.value, tab.instanceId])

  try {
    const res = await API.getAgentHistory(tab.instanceId)
    if (res.messages?.length) {
      tab.messages = res.messages.map(m => ({
        role: m.role as Message['role'],
        content: m.content,
        sender: m.role === 'assistant' ? tab.name : undefined,
      }))
    }
  } catch {
    // 加载失败保持空消息
  } finally {
    _loadingAgents.value.delete(tab.instanceId)
    // 触发 ref 更新（Set 的 delete 不会自动触发）
    _loadingAgents.value = new Set(_loadingAgents.value)
  }
}

declare global {
  interface WindowEventMap {
    token: CustomEvent<StreamChunk>
  }
}
