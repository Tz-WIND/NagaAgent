<script setup lang="ts">
import ScrollPanel from 'primevue/scrollpanel'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { ForumPost, SortMode, TimeOrder } from './types'
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

async function loadPosts() {
  const res = await fetchPosts(sortMode.value, 1, 20, timeOrder.value, yearMonth.value)
  posts.value = res.items
  totalComments.value = res.items.reduce((sum, p) => sum + p.commentsCount, 0)
}

watch([sortMode, timeOrder, yearMonth], () => loadPosts())
onMounted(() => loadPosts())

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

          <div v-if="!posts.length" class="text-white/30 text-sm text-center py-8">
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
