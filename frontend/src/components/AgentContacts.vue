<script setup lang="ts">
import { nextTick, ref } from 'vue'
import API from '@/api/core'
import back from '@/assets/icons/back.png'
import { agentContacts, loadAgentContacts, nextAgentNumber, openAgentTab, tabs } from '@/utils/session'

const backIcon = back

const collapsed = ref(false)
const adding = ref(false)

// 右键菜单
const contextMenu = ref<{ show: boolean, x: number, y: number, agentId: string, agentName: string }>({
  show: false, x: 0, y: 0, agentId: '', agentName: '',
})

// 重命名
const renamingId = ref<string | null>(null)
const renameValue = ref('')
const renameInputRef = ref<HTMLInputElement | null>(null)

function handleClick(agent: { id: string, name: string, running: boolean, created_at: number }) {
  openAgentTab(agent)
}

function handleContextMenu(e: MouseEvent, agent: { id: string, name: string }) {
  e.preventDefault()
  contextMenu.value = { show: true, x: e.clientX, y: e.clientY, agentId: agent.id, agentName: agent.name }
}

function closeContextMenu() {
  contextMenu.value.show = false
}

function startRenameFromIcon(agent: { id: string, name: string }) {
  renamingId.value = agent.id
  renameValue.value = agent.name
  nextTick(() => renameInputRef.value?.focus())
}

function startRenameFromMenu() {
  renamingId.value = contextMenu.value.agentId
  renameValue.value = contextMenu.value.agentName
  closeContextMenu()
  nextTick(() => renameInputRef.value?.focus())
}

async function finishRename(agentId: string) {
  const newName = renameValue.value.trim()
  if (!newName) {
    renamingId.value = null
    return
  }
  const contact = agentContacts.value.find(a => a.id === agentId)
  const oldName = contact?.name
  if (newName !== oldName) {
    try {
      await API.renameAgent(agentId, newName)
      // 更新通讯录
      if (contact) contact.name = newName
      // 同步到已打开的 tab + 消息中的 sender
      const tab = tabs.value.find(t => t.instanceId === agentId)
      if (tab) {
        tab.name = newName
        for (const msg of tab.messages) {
          if (msg.sender === oldName) msg.sender = newName
        }
      }
    }
    catch { /* ignore */ }
  }
  renamingId.value = null
}

async function deleteAgent() {
  const { agentId } = contextMenu.value
  closeContextMenu()
  try {
    await API.deleteAgent(agentId)
    // 从 tabs 中移除对应 tab
    const idx = tabs.value.findIndex(t => t.instanceId === agentId)
    if (idx > 0) tabs.value.splice(idx, 1)
    await loadAgentContacts()
  }
  catch { /* ignore */ }
}

async function addAgent() {
  if (adding.value) return
  adding.value = true
  try {
    const num = nextAgentNumber()
    await API.createAgent(`干员${num}`)
    await loadAgentContacts()
  }
  catch { /* ignore */ }
  finally {
    adding.value = false
  }
}

// 初始加载
loadAgentContacts()
</script>

<template>
  <div class="contacts-drawer" :class="{ collapsed }">
    <!-- 顶部栏：返回按钮 + 折叠按钮 -->
    <div class="top-bar">
      <img :src="backIcon" class="back-btn" alt="返回" @click="$router.back()">
      <button class="toggle-btn" :title="collapsed ? '展开通讯录' : '收起通讯录'" @click="collapsed = !collapsed">
        <svg
          xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
        >
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>
    </div>

    <!-- 角色列表（box 样式边框） -->
    <div v-show="!collapsed" class="contacts-body box">
      <div class="contacts-header">
        干员通讯录
      </div>

      <div class="contacts-items">
        <div
          v-for="agent in agentContacts" :key="agent.id"
          class="contact-item"
          @click="handleClick(agent)"
          @contextmenu="handleContextMenu($event, agent)"
        >
          <!-- 重命名输入态 -->
          <template v-if="renamingId === agent.id">
            <input
              ref="renameInputRef"
              v-model="renameValue"
              class="rename-input"
              @blur="finishRename(agent.id)"
              @keydown.enter="finishRename(agent.id)"
              @click.stop
            >
          </template>
          <!-- 正常展示态 -->
          <template v-else>
            <div class="contact-avatar">
              {{ agent.name.charAt(0) }}
            </div>
            <div class="contact-name">
              {{ agent.name }}
            </div>
            <div v-if="agent.running" class="running-dot" title="运行中" />
            <!-- 铅笔图标：点击进入重命名 -->
            <button class="rename-icon" title="重命名" @click.stop="startRenameFromIcon(agent)">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg>
            </button>
          </template>
        </div>

        <div v-if="agentContacts.length === 0" class="empty-hint">
          暂无干员
        </div>
      </div>

      <!-- 底部添加按钮 -->
      <button class="add-btn" :disabled="adding" @click="addAgent">
        + 新建干员
      </button>
    </div>

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="contextMenu.show"
        class="ctx-menu"
        :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      >
        <div class="ctx-item" @click="startRenameFromMenu">
          重命名
        </div>
        <div class="ctx-item ctx-danger" @click="deleteAgent">
          删除
        </div>
      </div>
      <div v-if="contextMenu.show" class="ctx-overlay" @click="closeContextMenu" />
    </Teleport>
  </div>
</template>

<style scoped>
.contacts-drawer {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 170px;
  min-width: 170px;
  transition: width 0.2s ease, min-width 0.2s ease;
  user-select: none;
  margin-right: 8px;
}

.contacts-drawer.collapsed {
  width: 40px;
  min-width: 40px;
}

/* 顶部栏：返回+折叠 */
.top-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  flex-shrink: 0;
}

.back-btn {
  width: var(--nav-back-width, 28px);
  cursor: pointer;
  transition: filter 0.2s ease;
  flex-shrink: 0;
}

.back-btn:hover {
  filter: brightness(1.35);
}

/* 圆形折叠按钮 */
.toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin-bottom: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.45);
  cursor: pointer;
  transition: color 0.2s, background 0.2s, border-color 0.2s;
  flex-shrink: 0;
}

.toggle-btn:hover {
  color: rgba(255, 255, 255, 0.85);
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.3);
}

/* 列表区域用 .box 九宫格边框 */
.contacts-body {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  width: 100%;
}

.contacts-header {
  padding: 6px 10px;
  font-size: 11px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.5px;
}

.contacts-items {
  flex: 1;
  overflow-y: auto;
  padding: 2px 4px;
}

/* 每个角色行 */
.contact-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 6px;
  margin: 2px 0;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}

.contact-item:hover {
  background: rgba(255, 255, 255, 0.07);
  border-color: rgba(255, 255, 255, 0.12);
}

.contact-avatar {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.7);
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.contact-name {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.75);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.running-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4ade80;
  flex-shrink: 0;
}

/* 铅笔重命名按钮 */
.rename-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.25);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s, background 0.15s;
  flex-shrink: 0;
}

.contact-item:hover .rename-icon {
  opacity: 1;
}

.rename-icon:hover {
  color: rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.1);
}

.rename-input {
  background: transparent;
  border: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.4);
  color: white;
  outline: none;
  width: 100%;
  font-size: 12px;
  padding: 4px 2px;
}

.empty-hint {
  color: rgba(255, 255, 255, 0.25);
  font-size: 11px;
  text-align: center;
  padding: 16px 0;
}

.add-btn {
  margin: 4px 8px 6px;
  padding: 5px 0;
  border: 1px dashed rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.4);
  font-size: 11px;
  cursor: pointer;
  transition: color 0.2s, border-color 0.2s;
}

.add-btn:hover:not(:disabled) {
  color: rgba(255, 255, 255, 0.7);
  border-color: rgba(255, 255, 255, 0.3);
}

.add-btn:disabled {
  opacity: 0.4;
  cursor: wait;
}

/* 右键菜单 */
.ctx-overlay {
  position: fixed;
  inset: 0;
  z-index: 999;
}

.ctx-menu {
  position: fixed;
  z-index: 1000;
  background: rgba(30, 30, 30, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  padding: 4px;
  backdrop-filter: blur(12px);
  min-width: 100px;
}

.ctx-item {
  padding: 6px 12px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
}

.ctx-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.ctx-danger:hover {
  color: #e74c3c;
}

/* 滚动条 */
.contacts-items::-webkit-scrollbar {
  width: 3px;
}

.contacts-items::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 2px;
}
</style>
