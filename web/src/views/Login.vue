<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">智能客服</h1>
      <p class="auth-sub">登录以继续使用</p>

      <div class="form-group">
        <label>用户名</label>
        <input
          v-model="username"
          class="form-control"
          placeholder="请输入用户名"
          @keydown.enter="doLogin"
        />
      </div>
      <div class="form-group">
        <label>密码</label>
        <input
          v-model="password"
          type="password"
          class="form-control"
          placeholder="请输入密码"
          @keydown.enter="doLogin"
        />
      </div>

      <div v-if="error" class="error-msg">{{ error }}</div>

      <button class="auth-btn" :disabled="loading" @click="doLogin">
        {{ loading ? '登录中...' : '登 录' }}
      </button>

      <div class="auth-links">
        <span>没有账号？</span>
        <a class="link" @click="goRegister">去注册</a>
      </div>

      <div class="default-tip">默认管理员账号：admin / agent_admin</div>
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
const error = ref('')
const loading = ref(false)

async function doLogin() {
  if (loading.value) return
  error.value = ''
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    const res = await api.login({ username: username.value.trim(), password: password.value })
    localStorage.setItem('auth_user', res.data?.username || username.value.trim())
    router.push('/').then(() => window.location.reload())
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function goRegister() {
  router.push('/register')
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

.default-tip {
  margin-top: 20px;
  padding-top: 12px;
  border-top: 1px dashed #E5E5E5;
  text-align: center;
  font-size: 12px;
  color: #BBB;
}
</style>
