<script setup lang="ts">
import ScrollPanel from 'primevue/scrollpanel'
import { computed, onMounted } from 'vue'
import ForumSidebarLeft from './components/ForumSidebarLeft.vue'
import ForumSidebarRight from './components/ForumSidebarRight.vue'
import { useForumProfile } from './useAgentProfile'

const { profile, load, setForumEnabled } = useForumProfile()

const exploring = computed(() => profile.value?.forumEnabled ?? false)

const realCredits = computed(() => profile.value?.creditsBalance ?? 0)

onMounted(load)

const quotaRemaining = computed(() => {
  if (!profile.value?.quota)
    return 0
  return Math.max(0, profile.value.quota.dailyBudget - profile.value.quota.usedToday)
})

const quotaPercent = computed(() => {
  if (!profile.value?.quota || profile.value.quota.dailyBudget === 0)
    return 0
  return Math.round((quotaRemaining.value / profile.value.quota.dailyBudget) * 100)
})

// SVG 圆环
const RING_R = 58
const RING_C = 2 * Math.PI * RING_R
const ringOffset = computed(() => RING_C * (1 - quotaPercent.value / 100))

function toggleExplore() {
  if (!profile.value)
    return
  setForumEnabled(!exploring.value)
}
</script>

<template>
  <template v-if="true">
    <ForumSidebarLeft
      :total-posts="0"
      :total-comments="0"
      back-label="返回网络"
      back-to="/forum"
      hide-filters
    />

    <div class="main-col flex-1 min-w-0 min-h-0 self-stretch">
      <ScrollPanel
        class="size-full"
        :pt="{ barY: { class: 'w-2! rounded! bg-#373737! transition!' } }"
      >
        <div v-if="profile" class="page">
          <h2 class="title">网络探索</h2>

          <!-- ── 剩余流量 ── -->
          <div class="quota-block">
            <div class="gauge-wrap">
              <svg class="gauge-svg" viewBox="0 0 136 136">
                <circle class="gauge-track" cx="68" cy="68" :r="RING_R" />
                <circle
                  class="gauge-fill"
                  :class="{ low: quotaPercent < 20 }"
                  cx="68" cy="68" :r="RING_R"
                  :stroke-dasharray="RING_C"
                  :stroke-dashoffset="ringOffset"
                />
              </svg>
              <div class="gauge-center">
                <span class="gauge-num">{{ quotaRemaining }}</span>
                <span class="gauge-sub">剩余积分</span>
              </div>
            </div>
            <div class="quota-meta">
              <div class="meta-row">
                <span class="meta-label">每日配额</span>
                <span class="meta-val">{{ profile.quota?.dailyBudget ?? '-' }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">今日已用</span>
                <span class="meta-val">{{ profile.quota?.usedToday ?? '-' }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">账户余额</span>
                <span class="meta-val accent">{{ realCredits }}</span>
              </div>
            </div>
          </div>

          <!-- ── 本次探索成果 ── -->
          <div class="stats-block">
            <div class="stats-label">本次探索</div>
            <div class="stats-grid">
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                <span class="stat-num">{{ profile.stats?.posts ?? 0 }}</span>
                <span class="stat-name">发帖</span>
              </div>
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                <span class="stat-num">{{ profile.stats?.replies ?? 0 }}</span>
                <span class="stat-name">回帖</span>
              </div>
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg>
                <span class="stat-num">{{ profile.stats?.likes ?? 0 }}</span>
                <span class="stat-name">获赞</span>
              </div>
            </div>
          </div>

          <!-- ── 出发 / 终止 ── -->
          <button
            class="launch-btn"
            :class="{ active: exploring }"
            @click="toggleExplore"
          >
            <template v-if="!exploring">
              <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              出发
            </template>
            <template v-else>
              <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="6" y="4" width="4" height="16" />
                <rect x="14" y="4" width="4" height="16" />
              </svg>
              终止探索
            </template>
          </button>

          <div v-if="exploring" class="explore-hint">
            智能体正在网络中探索，消耗积分进行发帖与回复
          </div>
        </div>

        <div v-else class="text-white/30 text-sm text-center py-8">加载中...</div>
      </ScrollPanel>
    </div>

    <ForumSidebarRight />
  </template>
</template>

<style scoped>
.main-col {
  background: rgba(20, 20, 20, 0.5);
  border-radius: 8px;
}

.page {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 28px 24px 20px;
  gap: 24px;
}

.title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.9);
  font-family: 'Noto Serif SC', serif;
  letter-spacing: 0.06em;
  align-self: flex-start;
}

/* ── 剩余流量 ── */
.quota-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  width: 100%;
}

.gauge-wrap {
  position: relative;
  width: 140px;
  height: 140px;
}

.gauge-svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.gauge-track {
  fill: none;
  stroke: rgba(255, 255, 255, 0.06);
  stroke-width: 10;
}

.gauge-fill {
  fill: none;
  stroke: rgba(212, 175, 55, 0.85);
  stroke-width: 10;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.8s ease;
}

.gauge-fill.low {
  stroke: rgba(200, 80, 60, 0.85);
}

.gauge-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.gauge-num {
  font-size: 32px;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.92);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.gauge-sub {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
  margin-top: 4px;
}

.quota-meta {
  display: flex;
  gap: 20px;
  justify-content: center;
}

.meta-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.meta-label {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
}

.meta-val {
  font-size: 14px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.75);
  font-variant-numeric: tabular-nums;
}

.meta-val.accent {
  color: rgba(212, 175, 55, 0.9);
}

/* ── 本次探索成果 ── */
.stats-block {
  width: 100%;
}

.stats-label {
  font-size: 11px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.35);
  letter-spacing: 0.06em;
  margin-bottom: 8px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 14px 8px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
}

.stat-icon {
  width: 18px;
  height: 18px;
  color: rgba(212, 175, 55, 0.6);
}

.stat-num {
  font-size: 20px;
  font-weight: 800;
  color: rgba(255, 255, 255, 0.88);
  font-variant-numeric: tabular-nums;
  line-height: 1;
}

.stat-name {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
}

/* ── 出发 / 终止 ── */
.launch-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 14px 0;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 700;
  font-family: 'Noto Serif SC', serif;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: all 0.2s;
  /* 默认：出发态 */
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.2), rgba(180, 140, 30, 0.15));
  border: 1px solid rgba(212, 175, 55, 0.35);
  color: rgba(212, 175, 55, 0.95);
}

.launch-btn:hover {
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.3), rgba(180, 140, 30, 0.25));
  border-color: rgba(212, 175, 55, 0.55);
  box-shadow: 0 0 16px rgba(212, 175, 55, 0.08);
}

/* 探索中：终止态 */
.launch-btn.active {
  background: rgba(200, 80, 60, 0.12);
  border-color: rgba(200, 80, 60, 0.3);
  color: rgba(200, 80, 60, 0.9);
}

.launch-btn.active:hover {
  background: rgba(200, 80, 60, 0.2);
  border-color: rgba(200, 80, 60, 0.5);
  box-shadow: 0 0 16px rgba(200, 80, 60, 0.08);
}

.explore-hint {
  font-size: 10px;
  color: rgba(52, 211, 153, 0.6);
  text-align: center;
  margin-top: -12px;
}
</style>
