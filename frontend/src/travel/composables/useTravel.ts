import type { TravelSession } from '@/travel/types'
import { useToast } from 'primevue/usetoast'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import coreApi from '@/api/core'

export const statusLabel: Record<string, string> = {
  pending: '准备中',
  running: '旅行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export function formatMinutes(m: number): string {
  const h = Math.floor(m / 60)
  const min = Math.round(m % 60)
  return h > 0 ? `${h}h ${min}m` : `${min}m`
}

export function formatDate(iso?: string): string {
  if (!iso)
    return '-'
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function useTravel() {
  const toast = useToast()

  const loading = ref(false)
  const travelSession = ref<TravelSession | null>(null)
  const isActive = ref(false)
  const historyList = ref<TravelSession[]>([])
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const isRunning = computed(() => travelSession.value?.status === 'running')
  const isCompleted = computed(() =>
    travelSession.value?.status === 'completed'
    || travelSession.value?.status === 'failed'
    || travelSession.value?.status === 'cancelled',
  )

  const timeProgress = computed(() => {
    if (!travelSession.value)
      return 0
    return Math.min(100, (travelSession.value.elapsedMinutes / travelSession.value.timeLimitMinutes) * 100)
  })

  const creditProgress = computed(() => {
    if (!travelSession.value)
      return 0
    return Math.min(100, (travelSession.value.creditsUsed / travelSession.value.creditLimit) * 100)
  })

  async function fetchStatus() {
    try {
      const res = await coreApi.getTravelStatus()
      travelSession.value = res.session
      isActive.value = res.active
    }
    catch {
      // ignore
    }
  }

  async function fetchHistory() {
    try {
      const res = await coreApi.getTravelHistory()
      historyList.value = res.sessions
    }
    catch {
      // ignore
    }
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(async () => {
      await fetchStatus()
      if (travelSession.value && !isActive.value) {
        stopPolling()
        toast.add({ severity: 'success', summary: '旅行完成', detail: `发现了 ${travelSession.value.discoveries?.length ?? 0} 个有趣内容`, life: 5000 })
        fetchHistory()
      }
    }, 30000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  async function startTravel(params: {
    agentId?: string
    timeLimitMinutes: number
    creditLimit: number
    wantFriends: boolean
    friendDescription?: string
    goalPrompt?: string
    deliverFullReport?: boolean
    deliverChannel?: string
    deliverTo?: string
  }) {
    loading.value = true
    try {
      await coreApi.startTravel(params)
      toast.add({ severity: 'success', summary: '出发！', detail: '旅行已开始', life: 3000 })
      await fetchStatus()
      startPolling()
    }
    catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '启动失败'
      toast.add({ severity: 'error', summary: '启动失败', detail: msg, life: 5000 })
    }
    finally {
      loading.value = false
    }
  }

  async function stopTravel() {
    try {
      await coreApi.stopTravel()
      toast.add({ severity: 'info', summary: '已停止', detail: '旅行已取消', life: 3000 })
      stopPolling()
      await fetchStatus()
      fetchHistory()
    }
    catch {
      toast.add({ severity: 'error', summary: '操作失败', detail: '停止旅行失败', life: 3000 })
    }
  }

  function viewSession(session: TravelSession) {
    travelSession.value = session
    isActive.value = false
  }

  onMounted(async () => {
    await fetchStatus()
    if (isActive.value) {
      startPolling()
    }
    fetchHistory()
  })

  onUnmounted(() => {
    stopPolling()
  })

  return {
    travelSession,
    isActive,
    isRunning,
    isCompleted,
    historyList,
    loading,
    timeProgress,
    creditProgress,
    startTravel,
    stopTravel,
    viewSession,
  }
}
