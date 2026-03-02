<script setup lang="ts">
import { Button } from 'primevue'
import type { TravelSession } from '@/travel/types'
import { formatDate, statusLabel } from '@/travel/composables/useTravel'
import TravelDiscoveryItem from './TravelDiscoveryItem.vue'

defineProps<{ session: TravelSession }>()
defineEmits<{ 'new-travel': [] }>()
</script>

<template>
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-2 text-white/80 text-base font-bold">
      <span
        class="inline-block w-2 h-2 rounded-full"
        :class="session.status === 'completed' ? 'bg-blue-400' : 'bg-red-400'"
      />
      {{ statusLabel[session.status] || session.status }}
    </div>
    <span class="text-white/30 text-xs">{{ formatDate(session.completedAt) }}</span>
  </div>

  <!-- 总结 -->
  <div v-if="session.summary" class="text-white/60 text-xs leading-relaxed bg-white/3 rounded-lg p-3">
    {{ session.summary }}
  </div>

  <!-- 错误信息 -->
  <div v-if="session.error" class="text-red-400/70 text-xs bg-red-500/5 rounded-lg p-3">
    {{ session.error }}
  </div>

  <!-- 发现列表 -->
  <div v-if="session.discoveries.length" class="flex flex-col gap-2">
    <div class="text-white/40 text-xs">
      发现 ({{ session.discoveries.length }})
    </div>
    <div class="flex flex-col gap-1.5 max-h-60 overflow-y-auto">
      <TravelDiscoveryItem
        v-for="(d, i) in session.discoveries"
        :key="i"
        :discovery="d"
        clickable
      />
    </div>
  </div>

  <!-- 社交互动 -->
  <div v-if="session.socialInteractions.length" class="flex flex-col gap-2">
    <div class="text-white/40 text-xs">
      社交互动 ({{ session.socialInteractions.length }})
    </div>
    <div class="flex flex-col gap-1.5">
      <div
        v-for="(s, i) in session.socialInteractions"
        :key="i"
        class="flex items-center gap-2 px-2 py-1.5 rounded bg-white/3 text-xs"
      >
        <span class="text-white/30 shrink-0">{{ s.type === 'post_created' ? '发帖' : s.type === 'reply_sent' ? '回复' : '好友' }}</span>
        <span class="text-white/50 truncate">{{ s.contentPreview }}</span>
      </div>
    </div>
  </div>

  <div class="border-t border-white/8 my-1" />

  <!-- 返回设置 -->
  <div class="flex justify-center">
    <Button
      label="开始新旅行"
      outlined
      class="px-6!"
      @click="$emit('new-travel')"
    />
  </div>
</template>
