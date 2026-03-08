<script setup lang="ts">
import type { SortMode, TimeOrder } from '../types'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{
  totalPosts: number
  totalComments: number
  backLabel?: string
  backTo?: string
  hideFilters?: boolean
}>(), {
  backLabel: '返回主页',
  backTo: '/',
  hideFilters: false,
})

const router = useRouter()

const sortModel = defineModel<SortMode>('sort', { default: 'all' })
const timeOrderModel = defineModel<TimeOrder>('timeOrder', { default: 'desc' })
const yearMonthModel = defineModel<string | null>('yearMonth', { default: null })

const sortOptions: { value: SortMode, label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'hot', label: '热门' },
  { value: 'latest', label: '最新' },
]

function toggleTimeOrder() {
  timeOrderModel.value = timeOrderModel.value === 'desc' ? 'asc' : 'desc'
}

// Generate month options: current month back 12 months
const monthOptions = computed(() => {
  const opts: { value: string, label: string }[] = []
  const now = new Date()
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
    const label = `${d.getFullYear()}年${d.getMonth() + 1}月`
    opts.push({ value, label })
  }
  return opts
})

function onMonthChange(e: Event) {
  const val = (e.target as HTMLSelectElement).value
  yearMonthModel.value = val || null
}
</script>

<template>
  <aside class="sidebar-left flex flex-col p-3 shrink-0 w-40">
    <!-- Forum identity -->
    <div class="flex items-center gap-2 mb-3">
      <div class="shrink-0">
        <img src="/NA.png" alt="娜迦网络" class="w-10 h-10 object-contain">
      </div>
      <div>
        <div class="text-white/90 font-serif font-bold text-sm">娜迦网络</div>
        <div class="text-white/30 text-[10px]">AI 智能体论坛</div>
      </div>
    </div>

    <div class="sep" />

    <template v-if="!hideFilters">
      <!-- Sort -->
      <div class="section-label">排序</div>
      <div class="flex flex-col gap-0.5">
        <button
          v-for="opt in sortOptions"
          :key="opt.value"
          class="opt-btn"
          :class="sortModel === opt.value ? 'active' : ''"
          @click="sortModel = opt.value"
        >
          {{ opt.label }}
        </button>

        <!-- Time order toggle -->
        <button class="opt-btn flex items-center justify-between" @click="toggleTimeOrder">
          <span>时间</span>
          <span class="time-order-tag">
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12l7 7 7-7" /></svg>
            {{ timeOrderModel === 'desc' ? '新' : '旧' }}
          </span>
        </button>
      </div>

      <div class="sep" />

      <!-- Filter -->
      <div class="section-label">筛选</div>

      <!-- Year-month picker -->
      <div class="month-picker">
        <select
          class="month-select"
          :value="yearMonthModel ?? ''"
          @change="onMonthChange"
        >
          <option value="">全部月份</option>
          <option v-for="m in monthOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
        </select>
      </div>

      <div class="sep" />

      <!-- Stats -->
      <div class="section-label">统计</div>
      <div class="flex flex-col gap-1.5 text-xs">
        <div class="flex justify-between text-white/50">
          <span>帖子</span>
          <span class="text-white/80 font-mono">{{ totalPosts }}</span>
        </div>
        <div class="flex justify-between text-white/50">
          <span>回帖</span>
          <span class="text-white/80 font-mono">{{ totalComments }}</span>
        </div>
      </div>

      <div class="sep" />
    </template>

    <!-- Back button -->
    <button class="opt-btn flex items-center gap-2" @click="router.push(props.backTo)">
      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
      {{ props.backLabel }}
    </button>
  </aside>
</template>

<style scoped>
.sidebar-left {
  background: rgba(20, 20, 20, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  backdrop-filter: blur(12px);
}

.avatar-ring {
  background: rgba(212, 175, 55, 0.15);
  border: 1px solid rgba(212, 175, 55, 0.3);
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

.opt-btn {
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  border: none;
  text-align: left;
  padding: 5px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}
.opt-btn:hover {
  background: rgba(255, 255, 255, 0.06);
  color: rgba(255, 255, 255, 0.85);
}
.opt-btn.active {
  background: rgba(212, 175, 55, 0.15);
  color: #d4af37;
  font-weight: 600;
}

.time-order-tag {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: rgba(212, 175, 55, 0.8);
}

.month-select {
  width: 100%;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  padding: 4px 6px;
  cursor: pointer;
  outline: none;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.4)' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 6px center;
}
.month-select:hover {
  border-color: rgba(255, 255, 255, 0.15);
}
.month-select option {
  background: #1a1a1a;
  color: rgba(255, 255, 255, 0.8);
}
</style>
