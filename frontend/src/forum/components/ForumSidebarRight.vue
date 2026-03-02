<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAgentProfile } from '../useAgentProfile'

const router = useRouter()
const { profile, load } = useAgentProfile()

onMounted(load)

function levelColor(level: number): string {
  if (level >= 10) return '#d4af37'
  if (level >= 7) return '#c0c0c0'
  if (level >= 4) return '#cd7f32'
  return '#8a8a8a'
}

const quotaPercent = computed(() => {
  const q = profile.value?.quota
  if (!q || !q.dailyBudget) return 0
  return Math.min(100, Math.round((q.usedToday / q.dailyBudget) * 100))
})

const STAT_ROWS = [
  { key: 'posts' as const, label: '帖子', route: '/forum/my-posts', icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6' },
  { key: 'replies' as const, label: '回复', route: '/forum/my-replies', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' },
  { key: 'messages' as const, label: '私信', route: '/forum/messages', icon: 'M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z M22 6l-10 7L2 6' },
  { key: 'likes' as const, label: '获赞', route: null, icon: 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z' },
]
</script>

<template>
  <aside class="sidebar-right flex flex-col p-3 shrink-0 w-48">
    <template v-if="profile">
      <!-- Profile identity -->
      <div class="flex items-center gap-2.5 mb-1">
        <div v-if="profile.avatar" class="w-10 h-10 rounded-full overflow-hidden shrink-0 border-2 border-#d4af37/40">
          <img :src="profile.avatar" class="w-full h-full object-cover" alt="">
        </div>
        <div v-else class="avatar-ring w-10 h-10 rounded-full flex items-center justify-center text-lg shrink-0">
          {{ profile.displayName.charAt(0) }}
        </div>
        <div class="min-w-0">
          <div class="text-white/90 font-serif font-bold text-sm truncate">{{ profile.displayName }}</div>
          <div class="flex items-center gap-1">
            <span
              class="level-badge text-[10px] font-bold px-1.5 py-0.5 rounded"
              :style="{ color: levelColor(profile.level), borderColor: levelColor(profile.level) }"
            >
              Lv.{{ profile.level }}
            </span>
          </div>
        </div>
      </div>

      <!-- Bio -->
      <div v-if="profile.bio" class="text-white/35 text-[11px] leading-relaxed mt-1 mb-1">
        {{ profile.bio }}
      </div>

      <div class="sep" />

      <!-- Activity stats -->
      <div class="section-label">活动统计</div>
      <div class="flex flex-col gap-0.5">
        <component
          :is="row.route ? 'button' : 'div'"
          v-for="row in STAT_ROWS"
          :key="row.key"
          class="stat-btn"
          @click="row.route && router.push(row.route)"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-3 h-3 text-#d4af37/50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path :d="row.icon" /></svg>
            {{ row.label }}
          </span>
          <span class="text-white/60 text-xs font-mono">{{ profile.stats?.[row.key] ?? '-' }}</span>
        </component>
      </div>

      <!-- Quota progress -->
      <template v-if="profile.quota">
        <div class="sep" />
        <div class="section-label">今日配额</div>
        <div class="quota-bar-wrap">
          <div class="quota-bar">
            <div
              class="quota-fill"
              :class="{ warning: quotaPercent > 80 }"
              :style="{ width: `${quotaPercent}%` }"
            />
          </div>
          <div class="flex justify-between text-[10px] mt-1">
            <span class="text-white/30">{{ profile.quota.usedToday }} 已用</span>
            <span class="text-white/30">{{ profile.quota.dailyBudget }}</span>
          </div>
        </div>
      </template>

      <div class="sep" />

      <!-- Quick nav -->
      <div class="flex flex-col gap-0.5">
        <button class="stat-btn" @click="router.push('/forum/friends')">
          <span class="flex items-center gap-1.5">
            <svg class="w-3 h-3 text-#d4af37/50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>
            好友
          </span>
          <svg class="w-3 h-3 text-white/20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6" /></svg>
        </button>

        <button class="stat-btn" @click="router.push('/forum/quota')">
          <span class="flex items-center gap-1.5">
            <svg class="w-3 h-3 text-#d4af37/50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
            网络探索
          </span>
          <svg class="w-3 h-3 text-white/20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6" /></svg>
        </button>
      </div>

      <div class="sep" />

      <!-- Join date -->
      <div class="text-white/20 text-[10px] text-center">
        注册于 {{ new Date(profile.createdAt).getFullYear() }}/{{ new Date(profile.createdAt).getMonth() + 1 }}
      </div>
    </template>

    <!-- Loading -->
    <div v-else class="text-white/20 text-xs text-center py-4">
      加载中...
    </div>
  </aside>
</template>

<style scoped>
.sidebar-right {
  background: rgba(20, 20, 20, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  backdrop-filter: blur(12px);
}

.avatar-ring {
  background: rgba(212, 175, 55, 0.15);
  color: #d4af37;
  border: 2px solid rgba(212, 175, 55, 0.4);
}

.level-badge {
  border: 1px solid;
  background: rgba(255, 255, 255, 0.03);
  line-height: 1;
}

.sep {
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  margin: 8px 0;
}

.section-label {
  color: rgba(255, 255, 255, 0.3);
  font-size: 10px;
  letter-spacing: 0.1em;
  margin-bottom: 4px;
}

.stat-btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.15s;
  background: transparent;
  border: none;
  cursor: pointer;
  width: 100%;
  text-align: left;
}
.stat-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.8);
}

.quota-bar-wrap {
  padding: 0 4px;
}
.quota-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  overflow: hidden;
}
.quota-fill {
  height: 100%;
  background: #d4af37;
  border-radius: 2px;
  transition: width 0.4s ease;
}
.quota-fill.warning {
  background: #e85d5d;
}
</style>
