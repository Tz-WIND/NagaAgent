import axios from 'axios'
import { ref } from 'vue'
import { authExpired } from '@/api'
import API from '@/api/core'
import { isNagaLoggedIn, refreshUserStats } from '@/composables/useAuth'
import { handleMusicCommand } from '@/composables/useMusicPlayer'
import { triggerAction } from '@/utils/live2dController'
import { getNagaTab } from '@/utils/session'

export const toolMessage = ref('')
export const openclawTasks = ref<Array<Record<string, any>>>([])
let timer: ReturnType<typeof setInterval> | null = null
let consecutiveFailures = 0

async function poll() {
  try {
    const [status, clawdbot, tasks, live2d, music] = await Promise.allSettled([
      API.getToolStatus(),
      API.getClawdbotReplies(),
      API.getOpenclawTasks(),
      API.getLive2dActions(),
      API.getMusicCommands(),
    ])

    // 轮询成功，重置失败计数
    consecutiveFailures = 0

    // 轮询时刷新积分
    if (isNagaLoggedIn.value) {
      refreshUserStats().catch(() => {})
    }

    if (status.status === 'fulfilled') {
      toolMessage.value = status.value.visible ? status.value.message : ''
    }

    if (clawdbot.status === 'fulfilled' && clawdbot.value.replies?.length) {
      const nagaTab = getNagaTab()
      for (const reply of clawdbot.value.replies) {
        nagaTab.messages.push({
          role: 'assistant',
          content: reply,
          sender: 'AgentServer',
        })
      }
    }

    if (tasks.status === 'fulfilled' && tasks.value.tasks) {
      openclawTasks.value = tasks.value.tasks
      const active = tasks.value.tasks.filter((t: any) => t.status === 'running' || t.status === 'pending')
      if (active.length > 0 && !toolMessage.value) {
        toolMessage.value = `AgentServer: ${active.length} 个任务执行中...`
      }
    }
    else if (
      tasks.status === 'rejected'
      && axios.isAxiosError(tasks.reason)
      && tasks.reason.response?.status === 503
    ) {
      openclawTasks.value = []
    }

    if (live2d.status === 'fulfilled' && live2d.value.actions?.length) {
      for (const action of live2d.value.actions) {
        triggerAction(action)
      }
    }

    if (music.status === 'fulfilled' && music.value.commands?.length) {
      for (const cmd of music.value.commands) {
        handleMusicCommand(cmd)
      }
    }
  }
  catch {
    consecutiveFailures++
    // 连续 3 次轮询失败且已登录 → 触发重新登录弹窗
    if (consecutiveFailures >= 3 && isNagaLoggedIn.value) {
      authExpired.value = true
      consecutiveFailures = 0 // 重置，避免反复触发
    }
  }
}

export function startToolPolling() {
  if (timer)
    return
  poll()
  timer = setInterval(poll, 2000)
}

export function stopToolPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  toolMessage.value = ''
}
