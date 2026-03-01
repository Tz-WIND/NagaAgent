<script setup lang="ts">
import { Button, ProgressBar } from 'primevue'
import type { TravelSession } from '@/travel/types'
import { formatMinutes } from '@/travel/composables/useTravel'
import TravelDiscoveryItem from './TravelDiscoveryItem.vue'

defineProps<{
  session: TravelSession
  timeProgress: number
  creditProgress: number
}>()

defineEmits<{ stop: [] }>()
</script>

<template>
  <div class="flex items-center gap-2 text-white/80 text-base font-bold">
    <span class="inline-block w-2 h-2 rounded-full bg-green-400 animate-pulse" />
    旅行进行中
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
