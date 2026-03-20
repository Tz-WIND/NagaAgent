<script setup lang="ts">
import type { ForumPost, SortMode, TimeOrder } from './types'
import ScrollPanel from 'primevue/scrollpanel'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ACCESS_TOKEN } from '@/api'
import { sessionRestored } from '@/composables/useAuth'
import { backendConnected } from '@/utils/config'
import { fetchPosts } from './api'
import ForumPostCard from './components/ForumPostCard.vue'
import ForumSidebarLeft from './components/ForumSidebarLeft.vue'
import ForumSidebarRight from './components/ForumSidebarRight.vue'

const router = useRouter()
const sortMode = ref<SortMode>('all')
const timeOrder = ref<TimeOrder>('desc')
const yearMonth = ref<string | null>(null)
const posts = ref<ForumPost[]>([])
const totalComments = ref(0)
const loadingPosts = ref(false)
const postsError = ref('')
let currentLoadId = 0

function formatForumError(e: any) {
  const detail = e?.response?.data?.detail
  if (e?.response?.status === 401) {
    return '登录状态已失效，请重新登录娜迦网络'
  }
  if (detail?.error === 'upstream_non_json_response') {
    return `社区服务暂不可用：上游返回 ${detail.statusCode || detail.status_code}，类型 ${detail.contentType || detail.content_type || 'unknown'}`
  }
  if (typeof detail === 'string' && detail.trim()) {
    return `加载失败: ${detail}`
  }
  if (detail?.message) {
    return `加载失败: ${detail.message}`
  }
  return `加载失败: ${e?.message || 'unknown error'}`
}

async function loadPosts() {
  const loadId = ++currentLoadId
  // 后端未就绪直接等待，不立刻报错
  if (!backendConnected.value)
    return

  loadingPosts.value = true

  // 未登录直接返回，不发请求
  if (!ACCESS_TOKEN.value) {
    postsError.value = '请先登录后使用娜迦网络'
    posts.value = []
    loadingPosts.value = false
    return
  }

  // 等待后端认证完成，避免 token 未就绪时 401
  if (!sessionRestored.value) {
    await new Promise<void>((resolve) => {
      const stop = watch(sessionRestored, (ready) => {
        if (ready) {
          stop()
          resolve()
        }
      })
      setTimeout(() => {
        stop()
        resolve()
      }, 5000)
    })
  }

  // 超时后再次检查（可能已被 401 处理清空）
  if (!ACCESS_TOKEN.value) {
    postsError.value = '请先登录后使用娜迦网络'
    loadingPosts.value = false
    return
  }

  try {
    if (!posts.value.length) {
      postsError.value = ''
    }
    let res
    try {
      res = await fetchPosts(sortMode.value, 1, 20, timeOrder.value, yearMonth.value)
    }
    catch (e: any) {
      const status = e?.response?.status
      if (status === 500 || status === 503) {
        await new Promise(resolve => setTimeout(resolve, 600))
        res = await fetchPosts(sortMode.value, 1, 20, timeOrder.value, yearMonth.value)
      }
      else {
        throw e
      }
    }
    if (loadId !== currentLoadId)
      return
    posts.value = res.items
    totalComments.value = res.items.reduce((sum, p) => sum + p.commentsCount, 0)
    postsError.value = ''
  }
  catch (e: any) {
    if (loadId !== currentLoadId)
      return
    if (!posts.value.length) {
      postsError.value = formatForumError(e)
    }
  }
  finally {
    if (loadId === currentLoadId) {
      loadingPosts.value = false
    }
  }
}

watch([sortMode, timeOrder, yearMonth], () => {
  void loadPosts()
})
watch([backendConnected, ACCESS_TOKEN], ([connected, token]) => {
  if (connected && token) {
    void loadPosts()
  }
})
onMounted(() => {
  if (backendConnected.value && ACCESS_TOKEN.value) {
    void loadPosts()
  }
})

function openPost(id: string) {
  router.push(`/forum/${id}`)
}
</script>

<template>
  <template v-if="true">
    <!-- Left sidebar -->
    <ForumSidebarLeft
      v-model:sort="sortMode"
      v-model:time-order="timeOrder"
      v-model:year-month="yearMonth"
      :total-posts="posts.length"
      :total-comments="totalComments"
    />

    <!-- Main post list -->
    <div class="main-col flex-1 min-w-0 min-h-0 self-stretch">
      <ScrollPanel
        class="size-full"
        :pt="{
          barY: { class: 'w-2! rounded! bg-#373737! transition!' },
        }"
      >
        <div class="flex flex-col gap-3 p-2">
          <ForumPostCard
            v-for="post in posts"
            :key="post.id"
            :post="post"
            @click="openPost"
          />

          <div v-if="postsError" class="text-red-300/80 text-sm text-center py-8">
            {{ postsError }}
          </div>

          <div v-else-if="loadingPosts" class="text-white/30 text-sm text-center py-8">
            加载中...
          </div>

          <div v-else-if="!posts.length" class="text-white/30 text-sm text-center py-8">
            暂无帖子
          </div>
        </div>
      </ScrollPanel>
    </div>

    <!-- Right sidebar -->
    <ForumSidebarRight />
  </template>
</template>

<style scoped>
.main-col {
  background: rgba(20, 20, 20, 0.5);
  border-radius: 8px;
}
</style>
