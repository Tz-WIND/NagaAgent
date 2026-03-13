<script setup lang="ts">
import { Button, InputNumber, Select, Textarea, ToggleSwitch } from 'primevue'
import { computed, onMounted, ref, watch } from 'vue'
import ConfigItem from '@/components/ConfigItem.vue'
import { agentContacts, loadAgentContacts } from '@/utils/session'

defineProps<{ loading: boolean }>()
const emit = defineEmits<{
  start: [params: { agentId?: string, timeLimitMinutes: number, creditLimit: number, wantFriends: boolean, friendDescription?: string, goalPrompt?: string }]
}>()

const timeLimit = ref(300)
const creditLimit = ref(1000)
const wantFriends = ref(true)
const friendDescription = ref('')
const goalPrompt = ref('追踪 AI、技术与互联网的最新热点，优先关注仍在持续发酵的话题和一手来源')
const selectedAgentId = ref('')
const openclawAgents = computed(() => agentContacts.value.filter(agent => (agent.engine || 'openclaw') === 'openclaw'))

watch(openclawAgents, (agents) => {
  if (!selectedAgentId.value && agents.length > 0) {
    selectedAgentId.value = agents[0]!.id
  }
  if (selectedAgentId.value && !agents.some(agent => agent.id === selectedAgentId.value)) {
    selectedAgentId.value = agents[0]?.id || ''
  }
}, { immediate: true })

onMounted(() => {
  void loadAgentContacts()
})

function onStart() {
  emit('start', {
    agentId: selectedAgentId.value || undefined,
    timeLimitMinutes: timeLimit.value,
    creditLimit: creditLimit.value,
    wantFriends: wantFriends.value,
    friendDescription: friendDescription.value || undefined,
    goalPrompt: goalPrompt.value || undefined,
  })
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="text-white/60 text-xs pl-1">
      探索干员
    </div>
    <Select
      v-model="selectedAgentId"
      :options="openclawAgents"
      option-label="name"
      option-value="id"
      placeholder="选择一个通讯录中的干员"
      :disabled="!openclawAgents.length"
    />
    <div v-if="!openclawAgents.length" class="text-xs text-white/30 pl-1">
      需要先创建一个 OpenClaw 干员，探索才会使用该干员的人格模板和实例记忆。
    </div>
  </div>

  <div class="border-t border-white/8 my-1" />

  <div class="flex flex-col gap-2">
    <div class="text-white/60 text-xs pl-1">
      探索方向
    </div>
    <Textarea
      v-model="goalPrompt"
      rows="4"
      class="resize-none"
      placeholder="告诉 OpenClaw 你想让它重点探索的方向，例如：最新 AI 产品、海外开发者热点、前沿论文、设计趋势等"
    />
  </div>

  <div class="border-t border-white/8 my-1" />

  <!-- 时间限制 -->
  <ConfigItem name="时间限制" description="本次旅行的最长时间">
    <InputNumber
      v-model="timeLimit"
      :min="5" :max="720" suffix=" 分钟"
      show-buttons
    />
  </ConfigItem>

  <!-- 积分限制 -->
  <ConfigItem name="积分限制" description="本次旅行最多消耗的积分">
    <InputNumber
      v-model="creditLimit"
      :min="10" :max="10000" suffix=" 积分"
      show-buttons
    />
  </ConfigItem>
  <div class="text-xs text-white/30 -mt-2 pl-1">
    1元 = 100积分，通过 NagaBusiness 计费系统消耗
  </div>

  <div class="border-t border-white/8 my-1" />

  <!-- 社交开关 -->
  <ConfigItem name="想认识朋友吗？" description="允许 Naga 在旅途中与其他 AI 社交互动">
    <ToggleSwitch v-model="wantFriends" />
  </ConfigItem>

  <!-- 交友描述 -->
  <div v-show="wantFriends" class="flex flex-col gap-2">
    <div class="text-white/60 text-xs pl-1">
      想认识什么朋友？
    </div>
    <Textarea
      v-model="friendDescription"
      rows="3"
      class="resize-none"
      placeholder="描述你希望 Naga 认识的朋友类型..."
    />
  </div>

  <!-- 出发按钮 -->
  <div class="flex justify-center mt-2">
    <Button
      label="出发！"
      class="px-8!"
      :loading="loading"
      :disabled="!openclawAgents.length || !selectedAgentId"
      @click="onStart"
    />
  </div>
</template>
