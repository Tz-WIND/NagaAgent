<script setup lang="ts">
import { Button, InputText, Textarea } from 'primevue'
import Select from 'primevue/select'
import { computed, ref, watch } from 'vue'

interface AgentOption {
  id: string
  name: string
}

const props = defineProps<{
  visible: boolean
  /** 编辑模式时传入已有数据 */
  editData?: {
    name: string
    displayName: string
    description: string
    config: Record<string, any>
    scope?: 'public' | 'private'
    agentId?: string
  } | null
  agents?: AgentOption[]
  initialScope?: 'public' | 'private'
  fixedScope?: 'public' | 'private'
  fixedAgentId?: string
  title?: string
}>()
const emit = defineEmits<{
  confirm: [data: { name: string, displayName: string, description: string, config: Record<string, any>, scope: 'public' | 'private', agentId?: string }]
  cancel: []
}>()

const name = ref('')
const displayName = ref('')
const description = ref('')
const jsonText = ref('')
const errorMsg = ref('')
const showExtra = ref(false)
const scope = ref<'public' | 'private'>('public')
const selectedAgentId = ref('')

const scopeOptions: Array<{ label: string, value: 'public' | 'private', description: string }> = [
  { label: '通用 MCP', value: 'public', description: '配置后会进入全局 MCP 列表，并做预热。' },
  { label: '专有 MCP', value: 'private', description: '只给单个干员使用，不会暴露给其他干员。' },
]

const isEdit = computed(() => !!props.editData)

// 当 dialog 打开或 editData 变化时，同步字段
watch(() => props.visible, (v) => {
  if (v && props.editData) {
    name.value = props.editData.name
    displayName.value = props.editData.displayName || props.editData.name
    description.value = props.editData.description || ''
    jsonText.value = JSON.stringify(props.editData.config || {}, null, 2)
    showExtra.value = !!(props.editData.description)
    scope.value = props.fixedScope || props.editData.scope || props.initialScope || 'public'
    selectedAgentId.value = props.fixedAgentId || props.editData.agentId || ''
  }
  else if (v) {
    name.value = ''
    displayName.value = ''
    description.value = ''
    jsonText.value = ''
    showExtra.value = false
    scope.value = props.fixedScope || props.initialScope || 'public'
    selectedAgentId.value = props.fixedAgentId || ''
  }
  errorMsg.value = ''
})

const canSubmit = computed(() => name.value.trim() && jsonText.value.trim())

function handleConfirm() {
  if (!name.value.trim()) {
    errorMsg.value = '请输入 MCP 标题'
    return
  }
  if (!jsonText.value.trim()) {
    errorMsg.value = '请输入 JSON 配置'
    return
  }
  if (scope.value === 'private' && !selectedAgentId.value) {
    errorMsg.value = '专有 MCP 必须绑定一个干员'
    return
  }
  try {
    const config = JSON.parse(jsonText.value)
    emit('confirm', {
      name: name.value.trim(),
      displayName: displayName.value.trim() || name.value.trim(),
      description: description.value.trim(),
      config,
      scope: scope.value,
      agentId: scope.value === 'private' ? selectedAgentId.value : undefined,
    })
  }
  catch {
    errorMsg.value = 'JSON 格式无效'
    return
  }
  errorMsg.value = ''
}

function handleCancel() {
  name.value = ''
  displayName.value = ''
  description.value = ''
  jsonText.value = ''
  scope.value = props.fixedScope || props.initialScope || 'public'
  selectedAgentId.value = props.fixedAgentId || ''
  errorMsg.value = ''
  emit('cancel')
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="visible" class="dialog-overlay" @click.self="handleCancel">
        <div class="dialog-card">
          <h2 class="dialog-title">
            {{ title || (isEdit ? '编辑 MCP 服务' : '添加 MCP 服务') }}
          </h2>
          <div class="dialog-form">
            <label class="dialog-label">MCP 标题（唯一标识）</label>
            <InputText
              v-model="name"
              :disabled="isEdit"
              placeholder="如 firecrawl-mcp"
              class="dialog-input"
              :class="{ 'op-50': isEdit }"
            />

            <template v-if="!fixedScope">
              <label class="dialog-label">MCP 范围</label>
              <Select
                v-model="scope"
                :options="scopeOptions"
                option-label="label"
                option-value="value"
                class="dialog-input"
              />
              <div class="dialog-hint">
                {{ scopeOptions.find(item => item.value === scope)?.description }}
              </div>
            </template>
            <div v-else class="dialog-hint">
              {{ scopeOptions.find(item => item.value === scope)?.description }}
            </div>

            <template v-if="scope === 'private' && !fixedAgentId">
              <label class="dialog-label">绑定干员</label>
              <Select
                v-model="selectedAgentId"
                :options="agents || []"
                option-label="name"
                option-value="id"
                class="dialog-input"
                placeholder="选择一个干员"
              />
            </template>

            <!-- 附加信息（可折叠） -->
            <div class="extra-toggle" @click="showExtra = !showExtra">
              <span class="extra-arrow">{{ showExtra ? '▾' : '▸' }}</span>
              <span>附加信息</span>
            </div>
            <div v-if="showExtra" class="extra-section">
              <label class="dialog-label">显示名称</label>
              <InputText
                v-model="displayName"
                placeholder="显示名称（可选）"
                class="dialog-input"
              />
              <label class="dialog-label mt-2">描述</label>
              <InputText
                v-model="description"
                placeholder="简短描述（可选）"
                class="dialog-input"
              />
            </div>

            <label class="dialog-label">JSON 配置</label>
            <Textarea
              v-model="jsonText"
              rows="8"
              placeholder="{\n  &quot;command&quot;: &quot;npx&quot;,\n  &quot;args&quot;: [&quot;-y&quot;, &quot;@mcp/server&quot;],\n  &quot;type&quot;: &quot;stdio&quot;\n}"
              class="dialog-input resize-none font-mono text-xs!"
            />

            <div v-if="errorMsg" class="dialog-error">
              {{ errorMsg }}
            </div>
          </div>
          <Button
            :label="isEdit ? '保存' : '确认添加'"
            :disabled="!canSubmit"
            class="dialog-btn"
            @click="handleConfirm"
          />
        </div>
        <div class="dialog-skip" @click="handleCancel">
          取消
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(6px);
}

.dialog-card {
  position: relative;
  z-index: 10000;
  width: 420px;
  max-height: 85vh;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  border: 1px solid rgba(212, 175, 55, 0.5);
  border-radius: 12px;
  background: rgba(20, 14, 6, 0.98);
  box-shadow: 0 0 60px rgba(0, 0, 0, 0.5), 0 0 40px rgba(212, 175, 55, 0.1);
}

/* 确保弹窗内的滚动条也在正确的层级 */
.dialog-card::-webkit-scrollbar {
  width: 8px;
}

.dialog-card::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
}

.dialog-card::-webkit-scrollbar-thumb {
  background: rgba(212, 175, 55, 0.4);
  border-radius: 4px;
}

.dialog-card::-webkit-scrollbar-thumb:hover {
  background: rgba(212, 175, 55, 0.6);
}

.dialog-title {
  margin: 0 0 1.5rem;
  font-size: 1.25rem;
  font-weight: 600;
  text-align: center;
  color: rgba(212, 175, 55, 0.9);
  letter-spacing: 0.05em;
}

.dialog-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.dialog-label {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
}

.dialog-input {
  width: 100%;
}

.dialog-hint {
  font-size: 0.74rem;
  line-height: 1.5;
  color: rgba(255, 255, 255, 0.42);
}

.dialog-error {
  font-size: 0.8rem;
  color: #e85d5d;
  text-align: center;
}

.dialog-btn {
  width: 100%;
  margin-top: 0.25rem;
  background: linear-gradient(135deg, rgba(212, 175, 55, 0.8), rgba(180, 140, 30, 0.8));
  border: none;
  color: #1a1206;
  font-weight: 600;
}

.dialog-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(212, 175, 55, 1), rgba(180, 140, 30, 1));
}

.dialog-skip {
  margin-top: 1rem;
  font-size: 0.8rem;
  text-align: center;
  color: rgba(212, 175, 55, 0.45);
  cursor: pointer;
  transition: color 0.2s;
}

.dialog-skip:hover {
  color: rgba(212, 175, 55, 0.8);
}

.extra-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.4);
  cursor: pointer;
  user-select: none;
  padding: 0.15rem 0;
}

.extra-toggle:hover {
  color: rgba(255, 255, 255, 0.7);
}

.extra-arrow {
  font-size: 0.6rem;
}

.extra-section {
  padding-left: 0.5rem;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
}

.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity 0.3s ease;
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}
</style>
