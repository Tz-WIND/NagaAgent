import type { ForumProfile } from './types'
import { ref, watch } from 'vue'
import { ACCESS_TOKEN } from '@/api'
import { sessionRestored } from '@/composables/useAuth'
import { fetchProfile, updateProfile } from './api'

const profile = ref<ForumProfile | null>(null)
let loading: Promise<void> | null = null

export function useForumProfile() {
  async function load() {
    if (profile.value)
      return

    // 未登录（无 token）直接返回，不发请求
    if (!ACCESS_TOKEN.value)
      return

    // 等待后端认证完成，避免 token 未就绪时 401
    if (!sessionRestored.value) {
      await new Promise<void>((resolve) => {
        const stop = watch(sessionRestored, (ready) => {
          if (ready) {
            stop()
            resolve()
          }
        })
        setTimeout(() => { stop(); resolve() }, 5000)
      })
    }

    // 超时后再次检查 token（可能已被 401 处理清空）
    if (!ACCESS_TOKEN.value)
      return

    if (!loading) {
      loading = fetchProfile().then((data) => {
        profile.value = data
      }).catch(() => {
        // 请求失败，允许后续重试
        loading = null
      })
    }
    await loading
  }

  async function reload() {
    loading = null
    profile.value = null
    await load()
  }

  async function setForumEnabled(enabled: boolean) {
    await updateProfile({ forumEnabled: enabled } as any)
    if (profile.value) {
      profile.value = { ...profile.value, forumEnabled: enabled }
    }
  }

  return { profile, load, reload, setForumEnabled }
}

// Backward-compatible alias
export function useAgentProfile() {
  return useForumProfile()
}
