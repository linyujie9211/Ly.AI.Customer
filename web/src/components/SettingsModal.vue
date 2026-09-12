<template>
  <div class="settings-overlay" @mousedown="onMaskMouseDown" @mouseup="onMaskMouseUp">
    <div class="settings-modal">
      <div class="settings-header">
        <h2>系统设置</h2>
        <button class="settings-close" title="关闭" @click="$emit('close')">✕</button>
      </div>

      <div class="settings-body">
        <aside class="settings-nav">
          <button
            v-for="item in navItems"
            :key="item.key"
            :class="['nav-item', { active: activeNav === item.key }]"
            @click="activeNav = item.key"
          >
            <span class="nav-icon">{{ item.icon }}</span>
            {{ item.label }}
          </button>
        </aside>

        <section class="settings-content">
          <Models v-if="activeNav === 'models'" />
          <KnowledgeBase v-if="activeNav === 'kb'" />
          <PluginsManage v-if="activeNav === 'plugins'" />
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import Models from '../views/Models.vue'
import KnowledgeBase from './KnowledgeBase.vue'
import PluginsManage from './PluginsManage.vue'

defineEmits(['close'])

const activeNav = ref('models')

const navItems = [
  { key: 'models', label: '模型配置', icon: '⚙' },
  { key: 'kb', label: '知识库', icon: '📚' },
  { key: 'plugins', label: '插件管理', icon: '🧩' }
]
</script>

<style scoped>
.settings-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 960;
}

.settings-modal {
  background: #FFFFFF;
  border-radius: 12px;
  width: 1200px;
  max-width: 96vw;
  height: 870px;
  max-height: 94vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.settings-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #E5E5E5;
  flex-shrink: 0;
}

.settings-header h2 {
  font-size: 17px;
  font-weight: 700;
  color: #1F1F1F;
}

.settings-close {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  font-size: 15px;
  cursor: pointer;
  color: #666;
  border-radius: 6px;
  transition: background 0.15s;
}

.settings-close:hover {
  background: #E5E5E5;
  color: #1F1F1F;
}

.settings-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.settings-nav {
  width: 170px;
  flex-shrink: 0;
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 9px 12px;
  border: none;
  background: transparent;
  color: #1F1F1F;
  font-size: 13px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}

.nav-item:hover {
  background: #F5F5F5;
}

.nav-item.active {
  background: #EBF3FE;
  color: #3B82F6;
}

.nav-icon {
  font-size: 14px;
  flex-shrink: 0;
}

.settings-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 16px 20px;
  border-left: 1px solid #F0F0F0;
}
</style>
