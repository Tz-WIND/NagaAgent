<script setup lang="ts">
import type { McpService, SkillCatalogItem } from '@/api/core'
import { useStorage } from '@vueuse/core'
import { Accordion, InputText, Select } from 'primevue'
import { computed, ref } from 'vue'
import API from '@/api/core'
import BoxContainer from '@/components/BoxContainer.vue'
import ConfigGroup from '@/components/ConfigGroup.vue'
import McpAddDialog from '@/components/McpAddDialog.vue'
import SkillAddDialog from '@/components/SkillAddDialog.vue'

const accordionValue = useStorage('accordion-skill', ['mcp', 'hub', 'local-cache', 'public-skills'])

const mcpServices = ref<McpService[]>([])
const mcpLoading = ref(true)
const showMcpDialog = ref(false)
const editingMcp = ref<{
  name: string
  displayName: string
  description: string
  config: Record<string, any>
  scope: 'public'
} | null>(null)

const publicMcpServices = computed(() => mcpServices.value.filter(service => service.scope === 'public'))
const mcpEnabledCount = computed(() => publicMcpServices.value.filter(service => service.enabled).length)
const mcpTotalCount = computed(() => publicMcpServices.value.length)

async function loadMcpServices() {
  mcpLoading.value = true
  try {
    const res = await API.getMcpServices()
    mcpServices.value = (res.services ?? []).filter(service => service.scope === 'public')
  }
  catch {
    mcpServices.value = []
  }
  finally {
    mcpLoading.value = false
  }
}

function openAddMcp() {
  editingMcp.value = null
  showMcpDialog.value = true
}

function openEditMcp(service: McpService) {
  if (service.source === 'builtin')
    return
  editingMcp.value = {
    name: service.name,
    displayName: service.displayName || service.name,
    description: service.description || '',
    config: service.config || {},
    scope: 'public',
  }
  showMcpDialog.value = true
}

async function onMcpConfirm(data: {
  name: string
  displayName: string
  description: string
  config: Record<string, any>
  scope: 'public' | 'private'
}) {
  try {
    if (editingMcp.value) {
      await API.updateMcpService(data.name, {
        config: data.config,
        displayName: data.displayName,
        description: data.description,
      })
    }
    else {
      await API.importMcpConfig({
        name: data.name,
        config: data.config,
        displayName: data.displayName,
        description: data.description,
        scope: 'public',
      })
    }
    showMcpDialog.value = false
    await loadMcpServices()
  }
  catch (error: any) {
    // eslint-disable-next-line no-alert
    alert(`操作失败: ${error?.response?.data?.detail || error?.message || '未知错误'}`)
  }
}

async function toggleMcpEnabled(service: McpService) {
  if (service.source === 'builtin')
    return
  const nextValue = !service.enabled
  service.enabled = nextValue
  try {
    await API.updateMcpService(service.name, { enabled: nextValue })
  }
  catch {
    service.enabled = !nextValue
  }
}

async function deleteMcp(service: McpService) {
  if (service.source === 'builtin')
    return
  try {
    await API.deleteMcpService(service.name)
    await loadMcpServices()
  }
  catch (error: any) {
    // eslint-disable-next-line no-alert
    alert(`删除失败: ${error?.response?.data?.detail || error?.message || '未知错误'}`)
  }
}

const skillCatalogLoading = ref(true)
const localCacheSkills = ref<SkillCatalogItem[]>([])
const publicSkills = ref<SkillCatalogItem[]>([])
const showSkillDialog = ref(false)
const skillDialogScope = ref<'cache' | 'public'>('public')
const remoteHub = ref<{
  status: string
  message: string
  baseUrl?: string
  skillEndpointTemplate?: string
  mcpEndpointTemplate?: string
}>({
  status: 'unknown',
  message: '尚未读取 Hub 配置。',
})

async function loadSkillCatalog() {
  skillCatalogLoading.value = true
  try {
    const res = await API.getSkillCatalog()
    remoteHub.value = res.catalog.remoteHub
    localCacheSkills.value = res.catalog.localCache.skills || []
    publicSkills.value = res.catalog.publicSkills.skills || []
  }
  catch {
    remoteHub.value = {
      status: 'error',
      message: '读取 Hub 配置失败。',
    }
    localCacheSkills.value = []
    publicSkills.value = []
  }
  finally {
    skillCatalogLoading.value = false
  }
}

function openSkillDialog(scope: 'cache' | 'public') {
  skillDialogScope.value = scope
  showSkillDialog.value = true
}

async function onSkillConfirm(data: { name: string, content: string, scope: 'cache' | 'public' | 'private', agentId?: string }) {
  try {
    await API.importScopedSkill(data)
    showSkillDialog.value = false
    await loadSkillCatalog()
  }
  catch (error: any) {
    // eslint-disable-next-line no-alert
    alert(`导入失败: ${error?.response?.data?.detail || error?.message || '未知错误'}`)
  }
}

async function deleteScopedSkill(skill: SkillCatalogItem) {
  const scope = skill.scope === 'public' ? 'public' : 'cache'
  try {
    await API.deleteSkill(skill.name, scope)
    await loadSkillCatalog()
  }
  catch (error: any) {
    // eslint-disable-next-line no-alert
    alert(`删除失败: ${error?.response?.data?.detail || error?.message || '未知错误'}`)
  }
}

function skillBadgeLabel(skill: SkillCatalogItem) {
  if (skill.source === 'openclaw-local')
    return 'OpenClaw 本地'
  if (skill.source === 'naga-cache')
    return 'Naga 缓存'
  if (skill.source === 'naga-public')
    return '公有'
  return skill.source
}

const hubSkillName = ref('')
const hubMcpName = ref('')
const hubSkillScope = ref<'cache' | 'public'>('public')
const hubSkillLoading = ref(false)
const hubMcpLoading = ref(false)
const hubSkillFeedback = ref<{ severity: 'success' | 'error', message: string } | null>(null)
const hubMcpFeedback = ref<{ severity: 'success' | 'error', message: string } | null>(null)

const hubSkillScopeOptions = [
  { label: '安装到公有 Skill', value: 'public', description: '安装后立即进入可共享的公有 Skill 列表。' },
  { label: '安装到本地缓存', value: 'cache', description: '先拉到本地缓存，后续再人工整理发布。' },
]

async function installHubSkillByName() {
  const name = hubSkillName.value.trim()
  if (!name) {
    hubSkillFeedback.value = { severity: 'error', message: '请输入 Skill 名称。' }
    return
  }

  hubSkillLoading.value = true
  hubSkillFeedback.value = null
  try {
    const res = await API.installHubSkill({
      name,
      scope: hubSkillScope.value,
    })
    hubSkillFeedback.value = {
      severity: 'success',
      message: res.message || `已安装 Skill: ${name}`,
    }
    hubSkillName.value = ''
    await loadSkillCatalog()
  }
  catch (error: any) {
    hubSkillFeedback.value = {
      severity: 'error',
      message: error?.response?.data?.detail || error?.message || '安装 Skill 失败',
    }
  }
  finally {
    hubSkillLoading.value = false
  }
}

async function installHubMcpByName() {
  const name = hubMcpName.value.trim()
  if (!name) {
    hubMcpFeedback.value = { severity: 'error', message: '请输入 MCP 名称。' }
    return
  }

  hubMcpLoading.value = true
  hubMcpFeedback.value = null
  try {
    const res = await API.installHubMcp({
      name,
      scope: 'public',
    })
    hubMcpFeedback.value = {
      severity: 'success',
      message: res.message || `已安装 MCP: ${name}`,
    }
    hubMcpName.value = ''
    await loadMcpServices()
  }
  catch (error: any) {
    hubMcpFeedback.value = {
      severity: 'error',
      message: error?.response?.data?.detail || error?.message || '安装 MCP 失败',
    }
  }
  finally {
    hubMcpLoading.value = false
  }
}

void loadMcpServices()
void loadSkillCatalog()
</script>

<template>
  <BoxContainer class="text-sm">
    <Accordion :value="accordionValue" class="pb-8" multiple>
      <ConfigGroup value="mcp" header="通用 MCP">
        <div class="grid gap-3 min-w-0 overflow-hidden">
          <div class="skill-placeholder">
            通用 MCP 会在全局注册，并在导入、更新、启用后自动预热。专有 MCP 请到干员通讯录里的设置弹窗中配置。
          </div>

          <div v-if="!mcpLoading && publicMcpServices.length > 0" class="mcp-summary">
            已配置 {{ mcpTotalCount }} 个通用 MCP · 当前启用 {{ mcpEnabledCount }} 个
          </div>

          <div v-if="mcpLoading" class="text-white/40 text-xs py-2">
            正在检查通用 MCP...
          </div>
          <template v-else>
            <div v-for="service in publicMcpServices" :key="service.name" class="mcp-item min-w-0" :class="{ 'mcp-disabled': !service.enabled }">
              <div class="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">
                <button
                  class="mcp-toggle"
                  :class="{ 'mcp-toggle-on': service.enabled, 'mcp-toggle-builtin': service.source === 'builtin' }"
                  :title="service.source === 'builtin' ? '内置服务（始终启用）' : (service.enabled ? '点击禁用' : '点击启用')"
                  @click="toggleMcpEnabled(service)"
                >
                  <span class="mcp-toggle-dot" />
                </button>
                <div class="min-w-0 flex-1 overflow-hidden">
                  <div class="flex items-center gap-1.5">
                    <span class="font-bold text-sm text-white truncate">{{ service.displayName }}</span>
                    <span v-if="service.source === 'builtin'" class="mcp-badge builtin">内置</span>
                    <span v-else class="mcp-badge external">通用</span>
                  </div>
                  <div v-if="service.description" class="text-xs op-40 truncate mt-0.5">{{ service.description }}</div>
                </div>
              </div>
              <div v-if="service.source !== 'builtin'" class="flex items-center gap-1 shrink-0 ml-2">
                <button class="mcp-action-btn" title="编辑" @click="openEditMcp(service)">
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg>
                </button>
                <button class="mcp-action-btn mcp-action-delete" title="删除" @click="deleteMcp(service)">
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /></svg>
                </button>
              </div>
            </div>
            <div v-if="publicMcpServices.length === 0" class="text-white/40 text-xs py-2">
              暂无通用 MCP
            </div>
          </template>

          <button class="add-btn" @click="openAddMcp">
            添加通用 MCP
          </button>
        </div>
      </ConfigGroup>

      <ConfigGroup value="hub" header="Naga Hub">
        <div class="grid gap-4 min-w-0 overflow-hidden">
          <div class="skill-placeholder">
            {{ remoteHub.message }}
          </div>

          <div class="hub-endpoint-card">
            <div class="hub-endpoint-title">
              当前客户端会按名字请求以下接口
            </div>
            <div class="hub-endpoint-line">
              Skill: <code>{{ remoteHub.skillEndpointTemplate || '/api/hub/skill/{skill_name}' }}</code>
            </div>
            <div class="hub-endpoint-line">
              MCP: <code>{{ remoteHub.mcpEndpointTemplate || '/api/hub/mcp/{mcp_name}' }}</code>
            </div>
            <div v-if="remoteHub.baseUrl" class="hub-endpoint-line">
              Base URL: <code>{{ remoteHub.baseUrl }}</code>
            </div>
          </div>

          <div class="hub-grid">
            <section class="hub-card">
              <div class="hub-card-title">
                按名称安装 Skill
              </div>
              <InputText v-model="hubSkillName" placeholder="例如：search" />
              <Select
                v-model="hubSkillScope"
                :options="hubSkillScopeOptions"
                option-label="label"
                option-value="value"
              />
              <div class="hub-note">
                {{ hubSkillScopeOptions.find(item => item.value === hubSkillScope)?.description }}
              </div>
              <div v-if="hubSkillFeedback" class="hub-feedback" :class="hubSkillFeedback.severity">
                {{ hubSkillFeedback.message }}
              </div>
              <button class="add-btn" :disabled="hubSkillLoading" @click="installHubSkillByName">
                {{ hubSkillLoading ? '安装中...' : '安装 Skill 模板' }}
              </button>
            </section>

            <section class="hub-card">
              <div class="hub-card-title">
                按名称安装 MCP
              </div>
              <InputText v-model="hubMcpName" placeholder="例如：firecrawl-mcp" />
              <div class="hub-note">
                Hub 拉下来的 MCP 会直接写成通用 MCP，并触发预热。专有 MCP 请在干员设置里单独配置。
              </div>
              <div v-if="hubMcpFeedback" class="hub-feedback" :class="hubMcpFeedback.severity">
                {{ hubMcpFeedback.message }}
              </div>
              <button class="add-btn" :disabled="hubMcpLoading" @click="installHubMcpByName">
                {{ hubMcpLoading ? '安装中...' : '安装 MCP 模板' }}
              </button>
            </section>
          </div>
        </div>
      </ConfigGroup>

      <ConfigGroup value="local-cache" header="本地技能缓存">
        <div class="grid gap-3 min-w-0 overflow-hidden">
          <div class="skill-placeholder">
            本地缓存适合先试运行，再决定要不要整理成公有 Skill。
          </div>

          <div v-if="skillCatalogLoading" class="text-white/40 text-xs py-2">
            正在加载缓存 Skill...
          </div>
          <template v-else>
            <div v-for="skill in localCacheSkills" :key="`${skill.source}:${skill.name}`" class="skill-item min-w-0">
              <div class="flex-1 min-w-0 overflow-hidden">
                <div class="flex items-center gap-2">
                  <div class="font-bold text-sm text-white truncate">{{ skill.name }}</div>
                  <span class="scope-badge">{{ skillBadgeLabel(skill) }}</span>
                </div>
                <div class="text-xs op-50 truncate">{{ skill.description || '暂无描述' }}</div>
              </div>
              <button class="skill-action-btn skill-action-delete" title="删除缓存 Skill" @click="deleteScopedSkill(skill)">
                删除
              </button>
            </div>
            <div v-if="!localCacheSkills.length" class="text-white/40 text-xs py-2">
              暂无本地缓存 Skill
            </div>
          </template>

          <button class="add-btn" @click="openSkillDialog('cache')">
            导入本地缓存 Skill
          </button>
        </div>
      </ConfigGroup>

      <ConfigGroup value="public-skills" header="公有 Skill">
        <div class="grid gap-3 min-w-0 overflow-hidden">
          <div class="skill-placeholder">
            公有 Skill 会被娜迦和多个干员共用。专有 Skill 请在干员设置里维护。
          </div>

          <div v-if="skillCatalogLoading" class="text-white/40 text-xs py-2">
            正在加载公有 Skill...
          </div>
          <template v-else>
            <div v-for="skill in publicSkills" :key="`${skill.source}:${skill.name}`" class="skill-item min-w-0">
              <div class="flex-1 min-w-0 overflow-hidden">
                <div class="flex items-center gap-2">
                  <div class="font-bold text-sm text-white truncate">{{ skill.name }}</div>
                  <span class="scope-badge">{{ skillBadgeLabel(skill) }}</span>
                </div>
                <div class="text-xs op-50 truncate">{{ skill.description || '暂无描述' }}</div>
              </div>
              <button class="skill-action-btn skill-action-delete" title="删除公有 Skill" @click="deleteScopedSkill(skill)">
                删除
              </button>
            </div>
            <div v-if="!publicSkills.length" class="text-white/40 text-xs py-2">
              暂无公有 Skill
            </div>
          </template>

          <button class="add-btn" @click="openSkillDialog('public')">
            导入公有 Skill
          </button>
        </div>
      </ConfigGroup>
    </Accordion>

    <McpAddDialog
      :visible="showMcpDialog"
      :edit-data="editingMcp"
      fixed-scope="public"
      title="添加通用 MCP"
      @confirm="onMcpConfirm"
      @cancel="showMcpDialog = false"
    />
    <SkillAddDialog
      :visible="showSkillDialog"
      :fixed-scope="skillDialogScope"
      :title="skillDialogScope === 'cache' ? '导入本地缓存 Skill' : '导入公有 Skill'"
      @confirm="onSkillConfirm"
      @cancel="showSkillDialog = false"
    />
  </BoxContainer>
</template>

<style scoped>
.mcp-summary {
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.35);
  padding: 0 0.25rem;
}

.mcp-item {
  display: flex;
  align-items: center;
  padding: 0.5rem 0.6rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  transition: background 0.2s;
}

.mcp-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.mcp-item.mcp-disabled {
  opacity: 0.45;
}

.mcp-toggle {
  position: relative;
  width: 28px;
  height: 16px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.15);
  border: none;
  cursor: pointer;
  transition: background 0.2s;
  flex-shrink: 0;
  padding: 0;
}

.mcp-toggle-on {
  background: rgba(212, 175, 55, 0.7);
}

.mcp-toggle-builtin {
  opacity: 0.5;
  cursor: default;
}

.mcp-toggle-dot {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.9);
  transition: transform 0.2s;
}

.mcp-toggle-on .mcp-toggle-dot {
  transform: translateX(12px);
}

.mcp-badge {
  font-size: 0.6rem;
  padding: 0 0.3rem;
  border-radius: 3px;
  line-height: 1.4;
  font-weight: 600;
  flex-shrink: 0;
}

.mcp-badge.builtin {
  color: rgba(74, 222, 128, 0.8);
  background: rgba(74, 222, 128, 0.1);
}

.mcp-badge.external {
  color: rgba(96, 165, 250, 0.8);
  background: rgba(96, 165, 250, 0.1);
}

.mcp-action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.3);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.mcp-action-btn:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.08);
}

.mcp-action-delete:hover {
  color: #e85d5d;
  background: rgba(232, 93, 93, 0.1);
}

.skill-item,
.hub-card {
  display: flex;
  align-items: center;
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  transition: background 0.2s;
}

.skill-item:hover,
.hub-card:hover {
  background: rgba(255, 255, 255, 0.08);
}

.skill-placeholder,
.hub-endpoint-card {
  padding: 0.75rem 0.85rem;
  border-radius: 8px;
  border: 1px dashed rgba(212, 175, 55, 0.28);
  background: rgba(212, 175, 55, 0.04);
  font-size: 0.76rem;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.6;
}

.hub-endpoint-title {
  font-weight: 700;
  color: rgba(255, 255, 255, 0.82);
  margin-bottom: 0.35rem;
}

.hub-endpoint-line code {
  font-size: 0.72rem;
}

.hub-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.85rem;
}

.hub-card {
  flex-direction: column;
  align-items: stretch;
  gap: 0.7rem;
}

.hub-card-title {
  font-size: 0.9rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.9);
}

.hub-note {
  font-size: 0.74rem;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.55;
}

.hub-feedback {
  padding: 0.6rem 0.7rem;
  border-radius: 8px;
  font-size: 0.74rem;
  line-height: 1.5;
}

.hub-feedback.success {
  color: rgba(74, 222, 128, 0.95);
  background: rgba(74, 222, 128, 0.08);
}

.hub-feedback.error {
  color: rgba(255, 141, 141, 0.95);
  background: rgba(255, 141, 141, 0.08);
}

.scope-badge {
  padding: 0 0.38rem;
  border-radius: 999px;
  background: rgba(212, 175, 55, 0.12);
  color: rgba(212, 175, 55, 0.82);
  font-size: 0.62rem;
  line-height: 1.6;
  font-weight: 700;
  flex-shrink: 0;
}

.skill-action-btn {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.46);
  font-size: 0.74rem;
  cursor: pointer;
  transition: color 0.15s ease;
}

.skill-action-delete:hover {
  color: #ff8d8d;
}

.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 0.6rem 0.75rem;
  border: 1px dashed rgba(212, 175, 55, 0.35);
  border-radius: 8px;
  background: transparent;
  color: rgba(212, 175, 55, 0.76);
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}

.add-btn:hover:not(:disabled) {
  border-color: rgba(212, 175, 55, 0.7);
  color: rgba(212, 175, 55, 1);
  background: rgba(212, 175, 55, 0.06);
}

.add-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

@media (max-width: 900px) {
  .hub-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
