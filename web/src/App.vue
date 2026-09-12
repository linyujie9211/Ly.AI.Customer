<template>
  <div class="app">
    <!-- 顶部标题栏（登录/注册页不显示） -->
    <header v-if="!isAuthPage" class="title-bar">
      <div class="title-text">智能客服</div>
    </header>

    <!-- 主内容区 -->
    <main class="content">
      <router-view />
    </main>

    <!-- 左下角：用户卡片 + 弹出菜单（登录/注册页不显示） -->
    <div v-if="!isAuthPage" class="user-area">
      <!-- 弹出菜单 -->
      <div v-if="showMenu" class="user-menu">
        <button class="menu-item" @click="openSettings">
          <svg class="menu-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/>
          </svg>
          系统设置
        </button>
        <button class="menu-item" @click="logout">
          <svg class="menu-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/>
          </svg>
          退出登录
        </button>
      </div>

      <!-- 用户卡片 -->
      <div class="user-card">
        <div class="avatar">{{ avatarText }}</div>
        <span class="user-name" :title="username">{{ username }}</span>
        <button class="menu-trigger" title="更多" @click.stop="showMenu = !showMenu">⋯</button>
      </div>

      <!-- 点击其他区域关闭菜单 -->
      <div v-if="showMenu" class="menu-mask" @click="showMenu = false"></div>
    </div>

    <!-- 系统设置弹窗 -->
    <SettingsModal v-if="showSettings" @close="showSettings = false" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SettingsModal from './components/SettingsModal.vue'

const route = useRoute()
const router = useRouter()

const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')
const username = ref(localStorage.getItem('auth_user') || '')
const avatarText = computed(() => username.value.charAt(0).toUpperCase())
const showMenu = ref(false)
const showSettings = ref(false)

function openSettings() {
  showMenu.value = false
  showSettings.value = true
}

function logout() {
  localStorage.removeItem('auth_user')
  username.value = ''
  router.push('/login')
}
</script>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #FFFFFF;
}

.title-bar {
  display: flex;
  align-items: center;
  padding: 0 16px;
  background: #FFFFFF;
  border-bottom: 1px solid #E5E5E5;
  min-height: 44px;
}

.title-text {
  font-size: 13px;
  font-weight: 600;
  color: #1F1F1F;
  white-space: nowrap;
}

.content {
  flex: 1;
  overflow: hidden;
}

/* 左下角用户卡片 + 弹出菜单 */
.user-area {
  position: fixed;
  left: 16px;
  bottom: 16px;
  z-index: 950;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #F5F5F5;
  border: 1px solid #E5E5E5;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #3B82F6;
  color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  flex-shrink: 0;
}

.user-name {
  font-size: 13px;
  color: #1F1F1F;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-trigger {
  border: none;
  background: transparent;
  color: #666;
  font-size: 18px;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
}

.menu-trigger:hover {
  background: #E5E5E5;
}

.user-menu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 2;
  min-width: 160px;
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.menu-item {
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

.menu-item:hover {
  background: #F5F5F5;
}

.menu-icon {
  color: #666;
  flex-shrink: 0;
}

/* 透明遮罩：点击空白处关闭菜单 */
.menu-mask {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 1;
  background: transparent;
}
</style>
