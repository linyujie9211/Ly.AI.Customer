<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">注册账号</h1>
      <p class="auth-sub">创建一个新的智能客服账号</p>

      <div class="form-group">
        <label>用户名</label>
        <input
          v-model="username"
          class="form-control"
          placeholder="至少 3 个字符"
          @keydown.enter="doRegister"
        />
      </div>
      <div class="form-group">
        <label>密码</label>
        <input
          v-model="password"
          type="password"
          class="form-control"
          placeholder="至少 6 个字符"
          @keydown.enter="doRegister"
        />
      </div>
      <div class="form-group">
        <label>确认密码</label>
        <input
          v-model="confirmPassword"
          type="password"
          class="form-control"
          placeholder="再次输入密码"
          @keydown.enter="doRegister"
        />
      </div>

      <div v-if="error" class="error-msg">{{ error }}</div>
      <div v-if="success" class="success-msg">{{ success }}</div>

      <button class="auth-btn" :disabled="loading" @click="doRegister">
        {{ loading ? '注册中...' : '注 册' }}
      </button>

      <div class="auth-links">
        <span>已有账号？</span>
        <a class="link" @click="goLogin">去登录</a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'

const router = useRouter()
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const error = ref('')
const success = ref('')
const loading = ref(false)

async function doRegister() {
  if (loading.value) return
  error.value = ''
  success.value = ''

  const name = username.value.trim()
  if (!name || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  if (name.length < 3) {
    error.value = '用户名至少 3 个字符'
    return
  }
  if (password.value.length < 6) {
    error.value = '密码至少 6 个字符'
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    await api.register({ username: name, password: password.value })
    success.value = '注册成功，即将跳转到登录页...'
    setTimeout(() => router.push('/login'), 1200)
  } catch (e) {
    error.value = e.response?.data?.detail || '注册失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function goLogin() {
  router.push('/login')
}
</script>

<style scoped>
.auth-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #F7F8FA;
}

.auth-card {
  width: 360px;
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 12px;
  padding: 32px 32px 24px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

.auth-title {
  font-size: 22px;
  font-weight: 700;
  color: #1F1F1F;
  text-align: center;
}

.auth-sub {
  font-size: 13px;
  color: #888;
  text-align: center;
  margin: 6px 0 24px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #1F1F1F;
  margin-bottom: 6px;
}

.form-control {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  font-size: 14px;
  background: #FFFFFF;
  color: #1F1F1F;
}

.form-control:focus {
  outline: none;
  border-color: #3B82F6;
}

.error-msg {
  background: #FEE2E2;
  color: #B91C1C;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 12px;
}

.success-msg {
  background: #DCFCE7;
  color: #15803D;
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 12px;
}

.auth-btn {
  width: 100%;
  padding: 10px;
  background: #3B82F6;
  color: #FFFFFF;
  border: none;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.15s;
}

.auth-btn:hover:not(:disabled) {
  background: #2563EB;
}

.auth-btn:disabled {
  background: #93C5FD;
  cursor: not-allowed;
}

.auth-links {
  margin-top: 16px;
  text-align: center;
  font-size: 13px;
  color: #888;
}

.link {
  color: #3B82F6;
  cursor: pointer;
  margin-left: 4px;
}

.link:hover {
  text-decoration: underline;
}
</style>
