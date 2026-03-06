import { ref } from 'vue'
import API from '@/api/core'
import { authExpired } from '@/api'
import { triggerAction } from '@/utils/live2dController'
import { MESSAGES } from '@/utils/session'
import { handleMusicCommand } from '@/composables/useMusicPlayer'
import { isNagaLoggedIn, refreshUserStats } from '@/composables/useAuth'

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
      for (const reply of clawdbot.value.replies) {
        MESSAGES.value.push({
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
