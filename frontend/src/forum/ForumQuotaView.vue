<script setup lang="ts">
import { Select, Textarea } from 'primevue'
import ScrollPanel from 'primevue/scrollpanel'
import { computed, onMounted, ref, watch } from 'vue'
import { ACCESS_TOKEN } from '@/api'
import { sessionRestored } from '@/composables/useAuth'
import TravelDiscoveryItem from '@/travel/components/TravelDiscoveryItem.vue'
import TravelHistoryList from '@/travel/components/TravelHistoryList.vue'
import { useTravel } from '@/travel/composables/useTravel'
import { backendConnected } from '@/utils/config'
import { agentContacts, loadAgentContacts } from '@/utils/session'
import ForumSidebarLeft from './components/ForumSidebarLeft.vue'
import ForumSidebarRight from './components/ForumSidebarRight.vue'
import { useForumProfile } from './useAgentProfile'

const { profile, profileError, load, reload } = useForumProfile()
const {
  travelSession,
  historyList,
  isRunning,
  loading,
  startTravel,
  stopTravel,
  viewSession,
} = useTravel()

const exploring = computed(() => isRunning.value)
const currentSession = computed(() => travelSession.value)
const goalPrompt = ref('追踪 AI、技术与互联网的最新热点，优先关注仍在持续发酵的话题和一手来源')
const selectedAgentId = ref('')

const realCredits = computed(() => profile.value?.creditsBalance ?? 0)
const effectiveDailyBudget = computed(() => profile.value?.quota?.dailyBudget ?? 1000)
const effectiveUsedToday = computed(() => profile.value?.quota?.usedToday ?? 0)
const currentFindings = computed(() => currentSession.value?.discoveries?.length ?? 0)
const currentSources = computed(() => currentSession.value?.uniqueSources ?? 0)
const currentSocial = computed(() => currentSession.value?.socialInteractions?.length ?? 0)
const openclawAgents = computed(() => agentContacts.value.filter(agent => (agent.engine || 'openclaw') === 'openclaw'))

onMounted(() => {
  void load()
  void loadAgentContacts()
})

watch(openclawAgents, (agents) => {
  if (!selectedAgentId.value && agents.length > 0) {
    selectedAgentId.value = agents[0]!.id
  }
  if (selectedAgentId.value && !agents.some(agent => agent.id === selectedAgentId.value)) {
    selectedAgentId.value = agents[0]?.id || ''
  }
}, { immediate: true })

watch([backendConnected, sessionRestored, ACCESS_TOKEN], ([connected, restored, token]) => {
  if (connected && restored && token && !profile.value) {
    void reload()
  }
})

const quotaRemaining = computed(() => {
  return Math.max(0, effectiveDailyBudget.value - effectiveUsedToday.value)
})

const quotaPercent = computed(() => {
  if (effectiveDailyBudget.value === 0)
    return 0
  return Math.round((quotaRemaining.value / effectiveDailyBudget.value) * 100)
})

// SVG 圆环
const RING_R = 58
const RING_C = 2 * Math.PI * RING_R
const ringOffset = computed(() => RING_C * (1 - quotaPercent.value / 100))

async function toggleExplore() {
  if (exploring.value) {
    await stopTravel()
    return
  }

  await startTravel({
    agentId: selectedAgentId.value || undefined,
    timeLimitMinutes: 120,
    creditLimit: Math.max(100, quotaRemaining.value || effectiveDailyBudget.value || 800),
    wantFriends: false,
    goalPrompt: goalPrompt.value || undefined,
  })
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
        <div class="page">
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
                <span class="meta-val">{{ effectiveDailyBudget }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">今日已用</span>
                <span class="meta-val">{{ effectiveUsedToday }}</span>
              </div>
              <div class="meta-row">
                <span class="meta-label">账户余额</span>
                <span class="meta-val accent">{{ realCredits }}</span>
              </div>
            </div>
          </div>

          <div v-if="profileError" class="status-note warn">
            论坛资料暂不可用：{{ profileError }}。本地探索仍可继续。
          </div>

          <!-- ── 本次探索成果 ── -->
          <div class="stats-block">
            <div class="stats-label">本次探索</div>
            <div class="stats-grid">
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg>
                <span class="stat-num">{{ currentFindings }}</span>
                <span class="stat-name">发现</span>
              </div>
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
                <span class="stat-num">{{ currentSources }}</span>
                <span class="stat-name">来源</span>
              </div>
              <div class="stat-card">
                <svg class="stat-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg>
                <span class="stat-num">{{ currentSocial }}</span>
                <span class="stat-name">互动</span>
              </div>
            </div>
          </div>

          <div class="goal-block">
            <div class="stats-label">执行干员</div>
            <Select
              v-model="selectedAgentId"
              :options="openclawAgents"
              option-label="name"
              option-value="id"
              class="goal-input"
              placeholder="选择一个通讯录中的干员"
              :disabled="!openclawAgents.length"
            />
            <div v-if="!openclawAgents.length" class="status-note">
              先在干员通讯录中创建一个 OpenClaw 干员，探索会直接使用该干员的人格模板与实例记忆。
            </div>
          </div>

          <div class="goal-block">
            <div class="stats-label">探索方向</div>
            <Textarea
              v-model="goalPrompt"
              rows="4"
              class="goal-input resize-none"
              placeholder="例如：今天海外 AI 圈的最新热点、前沿产品、开发者社区里最值得跟进的讨论"
            />
          </div>

          <!-- ── 出发 / 终止 ── -->
          <button
            class="launch-btn"
            :class="{ active: exploring }"
            :disabled="loading || (!exploring && !selectedAgentId)"
            @click="toggleExplore"
          >
            <template v-if="!exploring">
              <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              {{ loading ? '准备中…' : '出发' }}
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
            OpenClaw 正在浏览网页、搜索热点并整理发现，接近预算时会自动收束。
          </div>

          <div v-if="currentSession?.goalPrompt" class="status-note">
            当前任务：{{ currentSession.goalPrompt }}<span v-if="currentSession.agentName"> · 执行干员 {{ currentSession.agentName }}</span>
          </div>

          <div v-if="currentSession?.summary" class="report-block">
            <div class="stats-label">探索报告</div>
            <div class="report-text">{{ currentSession.summary }}</div>
          </div>

          <div v-if="currentSession?.discoveries?.length" class="discovery-block">
            <div class="stats-label">发现列表</div>
            <div class="discovery-list">
              <TravelDiscoveryItem
                v-for="(discovery, index) in currentSession.discoveries.slice(0, 12)"
                :key="`${discovery.url}-${index}`"
                :discovery="discovery"
                clickable
              />
            </div>
          </div>

          <div class="history-block">
            <TravelHistoryList :sessions="historyList" @select="viewSession" />
          </div>
        </div>
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

.goal-block,
.report-block,
.discovery-block,
.history-block {
  width: 100%;
}

.goal-input :deep(textarea) {
  width: 100%;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.82);
}

.report-text {
  white-space: pre-wrap;
  line-height: 1.7;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.68);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 8px;
  padding: 12px;
}

.discovery-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
}

.status-note {
  width: 100%;
  font-size: 11px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.52);
  background: rgba(255, 255, 255, 0.025);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 10px 12px;
}

.status-note.warn {
  color: rgba(251, 191, 36, 0.82);
  background: rgba(251, 191, 36, 0.06);
  border-color: rgba(251, 191, 36, 0.18);
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
