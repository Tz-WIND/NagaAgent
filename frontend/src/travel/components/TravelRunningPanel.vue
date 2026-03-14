<script setup lang="ts">
import type { TravelSession } from '@/travel/types'
import { Button, ProgressBar } from 'primevue'
import { formatMinutes } from '@/travel/composables/useTravel'
import TravelDiscoveryItem from './TravelDiscoveryItem.vue'

defineProps<{
  session: TravelSession
  timeProgress: number
  creditProgress: number
  lastUpdatedLabel: string
}>()

defineEmits<{ stop: [] }>()
</script>

<template>
  <div class="flex items-center gap-2 text-white/80 text-base font-bold">
    <span class="inline-block w-2 h-2 rounded-full bg-green-400 animate-pulse" />
    旅行进行中
  </div>

  <div v-if="session.goalPrompt" class="text-white/35 text-[11px] leading-relaxed bg-white/2 rounded-lg p-3">
    探索方向：{{ session.goalPrompt }}
  </div>

  <div class="grid grid-cols-2 gap-2 text-[11px]">
    <div class="rounded-lg bg-white/3 px-3 py-2 text-white/55">
      执行干员
      <div class="mt-1 text-white/80 text-xs">
        {{ session.agentName || '自动分配' }}
      </div>
    </div>
    <div class="rounded-lg bg-white/3 px-3 py-2 text-white/55">
      最近刷新
      <div class="mt-1 text-white/80 text-xs">
        {{ lastUpdatedLabel }}
      </div>
    </div>
    <div class="rounded-lg bg-white/3 px-3 py-2 text-white/55">
      累计发现
      <div class="mt-1 text-white/80 text-xs">
        {{ session.discoveries.length }} 条
      </div>
    </div>
    <div class="rounded-lg bg-white/3 px-3 py-2 text-white/55">
      来源去重
      <div class="mt-1 text-white/80 text-xs">
        {{ session.uniqueSources || 0 }} 个
      </div>
    </div>
  </div>

  <div
    v-if="session.wrapUpSent"
    class="rounded-lg border border-blue-400/15 bg-blue-500/6 px-3 py-2 text-[11px] leading-relaxed text-blue-100/75"
  >
    已进入收束阶段，正在整理最终报告并准备回传。
  </div>

  <div
    v-else-if="(session.idlePolls || 0) >= 2 && !session.discoveries.length"
    class="rounded-lg border border-amber-400/15 bg-amber-500/6 px-3 py-2 text-[11px] leading-relaxed text-amber-100/75"
  >
    暂时还没有新的可保留发现，当前更像是在搜索或等待工具返回，不是已经停止。
  </div>

  <!-- 时间进度 -->
  <div class="flex flex-col gap-1">
    <div class="flex justify-between text-xs text-white/50">
      <span>已用时间</span>
      <span>{{ formatMinutes(session.elapsedMinutes) }} / {{ formatMinutes(session.timeLimitMinutes) }}</span>
    </div>
    <ProgressBar :value="timeProgress" :show-value="false" class="h-2!" />
  </div>

  <!-- 积分进度 -->
  <div class="flex flex-col gap-1">
    <div class="flex justify-between text-xs text-white/50">
      <span>已用积分</span>
      <span>{{ session.creditsUsed }} / {{ session.creditLimit }}</span>
    </div>
    <ProgressBar :value="creditProgress" :show-value="false" class="h-2!" />
  </div>

  <!-- 实时发现 -->
  <div v-if="session.discoveries.length" class="flex flex-col gap-2">
    <div class="text-white/40 text-xs">
      发现 ({{ session.discoveries.length }})
    </div>
    <div class="flex flex-col gap-1.5 max-h-40 overflow-y-auto">
      <TravelDiscoveryItem
        v-for="(d, i) in session.discoveries.slice(-5)"
        :key="i"
        :discovery="d"
      />
    </div>
  </div>

  <!-- 停止按钮 -->
  <div class="flex justify-center mt-2">
    <Button
      label="停止旅行"
      severity="danger"
      outlined
      class="px-8!"
      @click="$emit('stop')"
    />
  </div>
</template>
