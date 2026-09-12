<template>
  <div class="home-layout">
    <!-- ============ 左侧：历史对话列表 ============ -->
    <aside class="sidebar">
      <button class="new-chat-btn" @click="startNewChat">
        <span class="icon-plus">+</span>
        <span>开启新对话</span>
      </button>

      <div class="history-list">
        <template v-for="group in historyGroups" :key="group.label">
          <div class="group-label">{{ group.label }}</div>
          <div
            v-for="item in group.items"
            :key="item.id"
            :class="['history-item', { active: currentId === item.id }]"
            @click="loadHistory(item)"
          >
            <span class="history-title">{{ item.title }}</span>
            <button class="history-more" @click.stop="toggleMenu(item.id)" title="更多">···</button>
            <div v-if="menuFor === item.id" class="history-menu" @click.stop>
              <button class="menu-item menu-del" @click.stop="removeHistory(item)">删除</button>
            </div>
          </div>
        </template>

        <div v-if="historyGroups.length === 0" class="empty-history">
          暂无历史对话
        </div>
      </div>
    </aside>

    <!-- ============ 右侧：对话区 ============ -->
    <section class="chat">
      <!-- 顶部客服信息条 -->
      <div class="chat-header" v-if="messages.length > 0">
        <div class="agent-badge">
          <span class="agent-dot"></span>
          智能客服
        </div>
        <div class="task-time" v-if="lastTaskSeconds">
          响应耗时 {{ lastTaskSeconds }}s
        </div>
      </div>

      <!-- 消息流 -->
      <div class="messages" ref="messagesRef" @contextmenu="onChatContextMenu">
        <!-- 会话轮数超限提示 -->
        <div v-if="historyExceeded" class="history-warn">
          <span>当前对话已超过 200 轮，上下文过长可能影响回答质量，建议点击「开启新对话」开始新的会话。</span>
          <button class="warn-btn" @click="startNewChat">开启新对话</button>
        </div>
        <!-- 欢迎态：尚未发起任何对话 -->
        <div v-if="messages.length === 0" class="welcome">
          <h2>您好，我是智能客服</h2>
          <p class="welcome-sub">有什么可以帮您的？请在下方输入您的问题，我会尽快为您解答。</p>
          <div class="welcome-cards">
            <div class="w-card">
              <div class="w-card-title">💬 在线咨询</div>
              <div class="w-card-desc">输入问题，智能客服即时解答</div>
            </div>
            <div class="w-card">
              <div class="w-card-title">🕘 历史会话</div>
              <div class="w-card-desc">对话自动保存，随时回看继续</div>
            </div>
            <div class="w-card">
              <div class="w-card-title">⚡ 流式回复</div>
              <div class="w-card-desc">回答实时生成，无需长时间等待</div>
            </div>
          </div>
        </div>

        <template v-for="(m, idx) in messages" :key="idx">
          <!-- 用户消息 -->
          <div v-if="m.role === 'user'" class="msg msg-user">
            <div class="msg-bubble user-bubble">{{ m.content }}</div>
          </div>

          <!-- 客服消息 -->
          <div v-else class="msg msg-agent">
            <div class="agent-badge inline">
              <span class="agent-dot"></span>
              智能客服
            </div>
            <div v-if="m.error" class="msg-bubble agent-bubble error-bubble">
              {{ m.error }}
            </div>
            <template v-else>
              <!-- 插件工具调用状态 -->
              <div v-if="m.toolStatus" class="tool-chip">
                <span class="tool-chip-icon">🔧</span>{{ m.toolStatus }}
              </div>

              <!-- 写工具待确认卡片 -->
              <div v-if="m.pending" class="tool-confirm-card">
                <div class="tcc-head">🛡️ 智能客服请求执行工具</div>
                <div class="tcc-summary">{{ m.pending.summary || m.pending.name }}</div>
                <div v-if="m.pendingState === 'wait'" class="tcc-actions">
                  <button class="tcc-btn ok" @click="confirmTool(m)">确认执行</button>
                  <button class="tcc-btn no" @click="cancelTool(m)">取消</button>
                </div>
                <div v-else-if="m.pendingState === 'running'" class="tcc-state">执行中…</div>
                <div v-else-if="m.pendingState === 'cancelled'" class="tcc-state">已取消</div>
              </div>

              <div v-if="m.text" class="msg-bubble agent-bubble">{{ m.text }}</div>

              <!-- 操作按钮（复制） -->
              <div class="msg-actions" v-if="m.done && m.text">
                <button class="icon-btn" title="复制" @click="copyText(m.text)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                </button>
              </div>
            </template>
          </div>
        </template>

        <!-- 加载中（流式输出开始后隐藏，由占位消息实时显示内容） -->
        <div v-if="loading && !streaming" class="msg msg-agent">
          <div class="agent-badge inline">
            <span class="agent-dot"></span>
            智能客服
          </div>
          <div class="msg-bubble agent-bubble loading-bubble">
            <span class="dot-pulse"></span>
            <span class="dot-pulse"></span>
            <span class="dot-pulse"></span>
          </div>
        </div>
      </div>

      <!-- 底部输入栏 -->
      <div class="composer">
        <div class="input-card">
          <textarea
            v-model="userQuery"
            class="input-area"
            :placeholder="messages.length === 0 ? '请输入您的问题，例如：如何申请退款？' : '继续追问...'"
            rows="2"
            @keydown.enter.exact.prevent="sendQuery"
          ></textarea>
          <div class="input-toolbar">
            <div class="tool-left"></div>
            <div class="tool-right">
              <select v-model="modelId" class="model-select">
                <option v-for="m in models" :key="m.id" :value="m.id">
                  {{ m.display_name || m.name }}
                </option>
              </select>
              <button
                class="send-btn"
                :disabled="loading || !modelId || !userQuery.trim()"
                @click="sendQuery"
                title="发送 (Enter)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4l-1.4 1.4L16.2 11H4v2h12.2l-5.6 5.6L12 20l8-8z"/></svg>
              </button>
            </div>
          </div>
        </div>

        <div v-if="!modelId" class="hint">
          请先在「设置 → 模型配置」中添加并启用至少一个模型。
        </div>
      </div>
    </section>

    <!-- 消息右键菜单 -->
    <div
      v-if="msgMenu.visible"
      class="ctx-menu"
      :style="{ left: msgMenu.x + 'px', top: msgMenu.y + 'px' }"
      @click.stop
      @contextmenu.prevent
    >
      <button
        v-for="(item, i) in msgMenu.items"
        :key="i"
        class="menu-item"
        @click="doCopyItem(item)"
      >{{ item.label }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import api from '../api'

const models = ref([])
const modelId = ref(null)
const userQuery = ref('')
const loading = ref(false)
const streaming = ref(false) // LLM 正在流式输出（隐藏加载动画气泡）
const messages = ref([])
const history = ref([]) // {id(后端session_id), title, ts}
const currentId = ref(null)
const sessionId = ref(null) // 后端会话 id（持久化用）
const lastTaskSeconds = ref(0)
const messagesRef = ref(null)
const menuFor = ref(null) // 当前打开菜单的历史项 id
const msgMenu = ref({ visible: false, x: 0, y: 0, items: [] }) // 消息右键菜单
const historyExceeded = ref(false) // 会话轮数超过上限

// 把历史按时间分组：昨天 / 7天内 / 30天内 / 更早
const historyGroups = computed(() => {
  const now = Date.now()
  const day = 86400000
  const buckets = { '昨天': [], '7 天内': [], '30 天内': [], '更早': [] }
  for (const h of history.value) {
    const dt = now - (h.ts || 0)
    if (dt < day) buckets['昨天'].push(h)
    else if (dt < 7 * day) buckets['7 天内'].push(h)
    else if (dt < 30 * day) buckets['30 天内'].push(h)
    else buckets['更早'].push(h)
  }
  return Object.entries(buckets)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }))
})

onMounted(async () => {
  try {
    const mRes = await api.listModels()
    const enabledModels = (mRes.data || []).filter(m => m.enabled)
    models.value = enabledModels
    // 优先选中持久化的默认模型（同类型互斥），否则取第一个启用的
    const def = enabledModels.find(m => m.is_default)
    if (enabledModels.length) modelId.value = def ? def.id : enabledModels[0].id
  } catch (e) {
    console.error('加载模型失败', e)
  }
  loadChatList()
})

// 点击其他区域关闭菜单
function onGlobalClick() {
  menuFor.value = null
  msgMenu.value.visible = false
}
onMounted(() => {
  window.addEventListener('click', onGlobalClick)
  window.addEventListener('resize', closeMsgMenu)
})
onUnmounted(() => {
  window.removeEventListener('click', onGlobalClick)
  window.removeEventListener('resize', closeMsgMenu)
})

// 消息区右键菜单：智能识别选中内容 / 消息气泡
function onChatContextMenu(e) {
  const items = []

  // 1. 优先：用户划选了文本
  const sel = String(window.getSelection ? window.getSelection() : '').trim()
  if (sel) {
    items.push({ label: '复制选中内容', text: sel })
  }

  // 2. 按右键位置识别消息气泡
  const t = e.target
  const bubble = t.closest ? t.closest('.msg-bubble') : null
  if (bubble && !sel) {
    const text = bubble.innerText.trim()
    if (text && !items.some(i => i.text === text)) {
      items.push({ label: '复制', text })
    }
  }

  // 没有可复制的目标 → 不拦截默认行为
  if (!items.length) return

  e.preventDefault()
  menuFor.value = null
  const menuW = 150
  const menuH = items.length * 34 + 8
  msgMenu.value = {
    visible: true,
    x: Math.min(e.clientX, window.innerWidth - menuW - 8),
    y: Math.min(e.clientY, window.innerHeight - menuH - 8),
    items
  }
}
function closeMsgMenu() {
  msgMenu.value.visible = false
}
async function doCopyItem(item) {
  try {
    await navigator.clipboard.writeText(item.text || '')
  } catch { /* ignore */ }
  closeMsgMenu()
}

function toggleMenu(id) {
  menuFor.value = menuFor.value === id ? null : id
}

// 从后端加载会话列表（持久化，刷新后仍在）
async function loadChatList() {
  try {
    const res = await api.listChats()
    const items = res.data?.items || []
    history.value = items.map(s => ({
      id: s.id,
      title: s.title || s.first_query || '新对话',
      ts: parseTime(s.updated_at || s.created_at)
    }))
  } catch (e) {
    console.error('加载会话列表失败', e)
  }
}

// 后端时间字符串（UTC）-> 毫秒时间戳
function parseTime(s) {
  if (!s) return Date.now()
  const t = Date.parse(String(s).replace(' ', 'T') + 'Z')
  return isNaN(t) ? Date.now() : t
}

function scrollToBottom() {
  nextTick(() => {
    const el = messagesRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function sendQuery() {
  if (loading.value || !modelId.value || !userQuery.value.trim()) return
  const query = userQuery.value.trim()

  messages.value.push({ role: 'user', content: query })
  userQuery.value = ''
  loading.value = true
  streaming.value = false
  lastTaskSeconds.value = 0
  scrollToBottom()

  const t0 = Date.now()
  // 占位的客服消息：LLM 增量实时填充，避免整体等待超时
  const phIdx = messages.value.length
  messages.value.push({ role: 'agent', text: '', streaming: true, done: false })
  const phMsg = () => messages.value[phIdx]

  try {
    // 首次提问先创建会话并绑定，保证请求失败重发时仍归属同一会话
    if (!sessionId.value) {
      const created = await api.createChat({
        title: query.slice(0, 20) || '新对话',
        model_id: modelId.value || null
      })
      sessionId.value = created.data?.id
      currentId.value = sessionId.value
    }

    // 流式接口（SSE）：不走 axios（不支持流式），用 fetch 读响应体
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model_id: modelId.value,
        session_id: sessionId.value,
        user_query: query
      })
    })
    if (!resp.ok || !resp.body) {
      let detail = `请求失败（HTTP ${resp.status}）`
      try {
        const j = await resp.json()
        if (j?.detail) detail = j.detail
      } catch { /* ignore */ }
      throw new Error(detail)
    }

    // 解析 SSE：按空行分帧，取 data: 行 JSON
    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    let finished = false
    while (!finished) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let sep
      while ((sep = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, sep)
        buf = buf.slice(sep + 2)
        const dataLine = frame.split('\n').find(l => l.startsWith('data:'))
        if (!dataLine) continue
        let ev
        try { ev = JSON.parse(dataLine.slice(5).trim()) } catch { continue }

        if (ev.type === 'session') {
          // 后端返回会话 id -> 绑定当前对话
          sessionId.value = ev.session_id
          currentId.value = ev.session_id
        } else if (ev.type === 'delta') {
          // LLM 文本增量：返回多少显示多少
          streaming.value = true
          const ph = phMsg()
          if (ph) {
            ph.toolStatus = null
            ph.text += ev.content || ''
            scrollToBottom()
          }
        } else if (ev.type === 'tool_start') {
          // 插件工具开始执行：显示状态提示
          const ph = phMsg()
          if (ph) ph.toolStatus = ev.label || ev.summary || '正在调用工具'
        } else if (ev.type === 'final') {
          // 完整结果：替换占位消息为正式渲染
          const secs = Math.max(1, Math.round((Date.now() - t0) / 1000))
          lastTaskSeconds.value = secs
          if (ev.history_exceeded !== undefined) {
            historyExceeded.value = !!ev.history_exceeded
          }
          if (ev.pending_tool) {
            // 写工具待确认：渲染确认卡片，等用户点击后再调 /api/chat/confirm
            messages.value.splice(phIdx, 1, {
              role: 'agent',
              pending: ev.pending_tool,
              pendingState: 'wait',
              done: true
            })
          } else {
            messages.value.splice(phIdx, 1, {
              role: 'agent',
              text: ev.text || '',
              model: ev.model || '',
              done: true
            })
          }
          finished = true
        } else if (ev.type === 'error') {
          messages.value.splice(phIdx, 1, { role: 'agent', error: ev.detail || '对话失败', done: true })
          finished = true
        }
      }
    }
    // 流意外中断（没收到 final/error）：保留已收到的文本
    if (!finished) {
      const ph = phMsg()
      if (ph && ph.text) {
        messages.value.splice(phIdx, 1, { role: 'agent', text: ph.text, done: true })
      } else {
        messages.value.splice(phIdx, 1, { role: 'agent', error: '连接中断，未收到完整回复', done: true })
      }
    }
  } catch (e) {
    messages.value.splice(phIdx, 1, {
      role: 'agent',
      error: e.message || '对话失败',
      done: true
    })
  } finally {
    loading.value = false
    streaming.value = false
    scrollToBottom()
    loadChatList() // 刷新侧边栏（标题/排序）
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // ignore
  }
}

// 确认/取消执行写工具：POST /api/chat/confirm（SSE），复用分帧解析逻辑
async function runConfirmStream(action, card) {
  if (!sessionId.value || card.pendingState !== 'wait') return
  card.pendingState = 'running'
  loading.value = true
  streaming.value = false
  lastTaskSeconds.value = 0
  const t0 = Date.now()
  const phIdx = messages.value.length
  messages.value.push({ role: 'agent', text: '', streaming: true, done: false })
  const phMsg = () => messages.value[phIdx]

  try {
    const resp = await fetch('/api/chat/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value, action })
    })
    if (!resp.ok || !resp.body) {
      let detail = `请求失败（HTTP ${resp.status}）`
      try {
        const j = await resp.json()
        if (j?.detail) detail = j.detail
      } catch { /* ignore */ }
      throw new Error(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    let finished = false
    while (!finished) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let sep
      while ((sep = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, sep)
        buf = buf.slice(sep + 2)
        const dataLine = frame.split('\n').find(l => l.startsWith('data:'))
        if (!dataLine) continue
        let ev
        try { ev = JSON.parse(dataLine.slice(5).trim()) } catch { continue }

        if (ev.type === 'delta') {
          streaming.value = true
          const ph = phMsg()
          if (ph) {
            ph.toolStatus = null
            ph.text += ev.content || ''
            scrollToBottom()
          }
        } else if (ev.type === 'tool_start') {
          const ph = phMsg()
          if (ph) ph.toolStatus = ev.label || ev.summary || '正在调用工具'
        } else if (ev.type === 'final') {
          const secs = Math.max(1, Math.round((Date.now() - t0) / 1000))
          lastTaskSeconds.value = secs
          if (ev.pending_tool) {
            // 链式写工具：又出现下一个待确认
            messages.value.splice(phIdx, 1, {
              role: 'agent',
              pending: ev.pending_tool,
              pendingState: 'wait',
              done: true
            })
          } else {
            messages.value.splice(phIdx, 1, {
              role: 'agent',
              text: ev.text || '',
              model: ev.model || '',
              done: true
            })
          }
          finished = true
        } else if (ev.type === 'error') {
          messages.value.splice(phIdx, 1, { role: 'agent', error: ev.detail || '执行失败', done: true })
          finished = true
        }
      }
    }
    if (!finished) {
      const ph = phMsg()
      if (ph && ph.text) {
        messages.value.splice(phIdx, 1, { role: 'agent', text: ph.text, done: true })
      } else {
        messages.value.splice(phIdx, 1, { role: 'agent', error: '连接中断，未收到完整回复', done: true })
      }
    }
  } catch (e) {
    messages.value.splice(phIdx, 1, {
      role: 'agent',
      error: e.message || '执行失败',
      done: true
    })
  } finally {
    loading.value = false
    streaming.value = false
    scrollToBottom()
    loadChatList()
  }
}

function confirmTool(m) {
  runConfirmStream('confirm', m)
}

function cancelTool(m) {
  runConfirmStream('cancel', m)
}

async function loadHistory(item) {
  currentId.value = item.id
  sessionId.value = item.id
  // 从后端拉取消息并映射为 UI 格式
  try {
    const res = await api.getChat(item.id)
    const list = res.data?.messages || []
    messages.value = list.map(m => m.role === 'user'
      ? { role: 'user', content: m.content || '' }
      : { role: 'agent', text: m.content || '', done: true })
    // 根据已加载消息判断是否超限
    historyExceeded.value = messages.value.filter(m => m.role === 'user').length > 200
  } catch (e) {
    console.error('加载会话消息失败', e)
    messages.value = []
    historyExceeded.value = false
  }
  scrollToBottom()
}

function startNewChat() {
  currentId.value = null
  sessionId.value = null
  messages.value = []
  historyExceeded.value = false
}

async function removeHistory(item) {
  menuFor.value = null
  try {
    await api.deleteChat(item.id)
    await loadChatList()
    if (sessionId.value === item.id) startNewChat()
  } catch (e) {
    console.error('删除会话失败', e)
  }
}
</script>

<style scoped>
.home-layout {
  display: flex;
  height: 100%;
  width: 100%;
  background: #FFFFFF;
  overflow: hidden;
}

/* ============ 左侧侧边栏 ============ */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  border-right: 1px solid #EFEFEF;
  padding: 12px 10px;
  overflow-y: auto;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 10px 12px;
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 999px;
  font-size: 14px;
  color: #1F1F1F;
  cursor: pointer;
  margin-bottom: 18px;
  transition: background 0.15s;
}
.new-chat-btn:hover { background: #F5F5F5; }
.icon-plus {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 1.5px solid #1F1F1F;
  border-radius: 50%;
  font-size: 13px;
  line-height: 1;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-label {
  font-size: 12px;
  color: #999;
  padding: 10px 8px 6px;
  font-weight: 400;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #1F1F1F;
  transition: background 0.12s;
}
.history-item:hover { background: #F3F3F3; }
.history-item.active {
  background: #EDEDED;
  font-weight: 500;
}
.history-title {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-right: 6px;
}
.history-more {
  background: transparent;
  border: none;
  color: #999;
  font-size: 16px;
  padding: 0 4px;
  cursor: pointer;
  visibility: hidden;
}
.history-item:hover .history-more,
.history-more:focus { visibility: visible; }

/* 历史项弹出菜单 */
.history-item { position: relative; }
.history-menu {
  position: absolute;
  right: 0;
  top: calc(100% + 2px);
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 4px;
  min-width: 96px;
  z-index: 50;
}
.menu-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  padding: 7px 12px;
  font-size: 13px;
  border-radius: 5px;
  cursor: pointer;
  color: #374151;
  font-family: inherit;
}
.menu-item:hover { background: #F3F4F6; }
.menu-item.menu-del { color: #EF4444; }
.menu-item.menu-del:hover { background: #FEF2F2; }

/* 消息右键菜单 */
.ctx-menu {
  position: fixed;
  background: #fff;
  border: 1px solid #E5E7EB;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  padding: 4px;
  min-width: 128px;
  z-index: 1100;
}

.empty-history {
  text-align: center;
  color: #BBB;
  font-size: 12px;
  padding: 20px;
}

/* ============ 右侧对话区 ============ */
.chat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #FFFFFF;
  overflow: hidden;
}

.chat-header {
  padding: 12px 24px;
  border-bottom: 1px solid #F0F0F0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.agent-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: #E8F5E9;
  color: #2E7D32;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.agent-badge.inline { margin-bottom: 8px; align-self: flex-start; }
.agent-dot {
  width: 14px; height: 14px;
  background: #2E7D32;
  border-radius: 3px;
  display: inline-block;
  position: relative;
}
.agent-dot::after {
  content: '';
  position: absolute;
  left: 3px; top: 4px;
  width: 8px; height: 6px;
  border: 1.5px solid #fff;
  border-radius: 1px;
  border-top: none; border-right: none;
}

.task-time {
  color: #888;
  font-size: 12px;
}

/* 消息流 */
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 12px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* 消息内容允许文本选择 */
.msg-bubble {
  user-select: text;
  -webkit-user-select: text;
  cursor: text;
}

/* 会话轮数超限提示 */
.history-warn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid #FCD34D;
  background: #FFFBEB;
  border-radius: 8px;
  font-size: 13px;
  color: #92400E;
}
.warn-btn {
  background: #F59E0B;
  color: #fff;
  border: none;
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.warn-btn:hover { background: #D97706; }

/* 欢迎态 */
.welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
}
.welcome h2 {
  font-size: 22px;
  font-weight: 600;
  color: #1F1F1F;
  margin-bottom: 8px;
}
.welcome-sub {
  color: #888;
  font-size: 13px;
  margin-bottom: 28px;
  max-width: 420px;
}
.welcome-cards {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}
.w-card {
  background: #FAFAFA;
  border: 1px solid #EFEFEF;
  border-radius: 10px;
  padding: 14px 18px;
  width: 170px;
  text-align: left;
}
.w-card-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
.w-card-desc { font-size: 12px; color: #888; }

/* 单条消息 */
.msg { display: flex; flex-direction: column; max-width: 100%; }
.msg-user { align-items: flex-end; }
.msg-agent { align-items: flex-start; }

.msg-bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.user-bubble {
  background: #F4F4F4;
  color: #1F1F1F;
  border-top-right-radius: 4px;
}
.agent-bubble {
  background: #FFFFFF;
  color: #1F1F1F;
  border: 1px solid #EFEFEF;
  border-top-left-radius: 4px;
}
.error-bubble {
  background: #FEE2E2;
  color: #B91C1C;
  border-color: #FCA5A5;
}

/* 插件工具调用状态 */
.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  background: #EBF3FE;
  color: #3B82F6;
  border-radius: 999px;
  font-size: 12px;
  align-self: flex-start;
  margin-bottom: 2px;
}
.tool-chip-icon { font-size: 12px; }

/* 写工具待确认卡片 */
.tool-confirm-card {
  max-width: 75%;
  border: 1px solid #FCD34D;
  background: #FFFBEB;
  border-radius: 10px;
  padding: 10px 14px;
}
.tcc-head {
  font-size: 13px;
  font-weight: 600;
  color: #92400E;
  margin-bottom: 4px;
}
.tcc-summary {
  font-size: 13px;
  color: #1F1F1F;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin-bottom: 8px;
}
.tcc-actions { display: flex; gap: 8px; }
.tcc-btn {
  border: none;
  border-radius: 6px;
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.15s;
}
.tcc-btn.ok { background: #10A37F; color: #fff; }
.tcc-btn.ok:hover { background: #0E8E6E; }
.tcc-btn.no { background: #fff; color: #666; border: 1px solid #E5E5E5; }
.tcc-btn.no:hover { background: #F5F5F5; }
.tcc-state { font-size: 12px; color: #999; }
.loading-bubble {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 14px 16px;
}
.dot-pulse {
  width: 6px; height: 6px; border-radius: 50%;
  background: #999;
  animation: pulse 1.2s infinite ease-in-out;
}
.dot-pulse:nth-child(2) { animation-delay: 0.2s; }
.dot-pulse:nth-child(3) { animation-delay: 0.4s; }
@keyframes pulse {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-3px); }
}

/* 操作按钮组 */
.msg-actions {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  margin-left: 4px;
}
.icon-btn {
  background: transparent;
  border: none;
  color: #999;
  width: 26px;
  height: 26px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s;
}
.icon-btn:hover {
  background: #F0F0F0;
  color: #1F1F1F;
}

/* ============ 底部输入栏 ============ */
.composer {
  padding: 10px 24px 16px;
  background: #FFFFFF;
  border-top: 1px solid #F0F0F0;
}

.input-card {
  border: 1px solid #E5E5E5;
  border-radius: 14px;
  background: #FFFFFF;
  padding: 10px 12px;
  transition: border-color 0.15s;
}
.input-card:focus-within { border-color: #3B82F6; }

.input-area {
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-family: inherit;
  font-size: 14px;
  color: #1F1F1F;
  background: transparent;
  line-height: 1.5;
  min-height: 44px;
  max-height: 160px;
  padding: 4px 4px 8px;
}
.input-area::placeholder { color: #B0B0B0; }

.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid #F0F0F0;
  padding-top: 6px;
}
.tool-left, .tool-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.model-select {
  font-size: 12px;
  color: #888;
  margin-right: 6px;
  white-space: nowrap;
  background: transparent;
  border: none;
  outline: none;
  cursor: pointer;
  font-family: inherit;
  padding: 2px 4px;
  border-radius: 4px;
  max-width: 220px;
  direction: rtl;
  text-align: right;
}
.model-select:hover { color: #1F1F1F; background: #F5F5F5; }
.model-select option { direction: ltr; text-align: left; }

.send-btn {
  background: #10A37F;
  color: #fff;
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s;
}
.send-btn:disabled { background: #C8E6DD; cursor: not-allowed; }
.send-btn:hover:not(:disabled) { background: #0E8E6E; }

.hint {
  font-size: 12px;
  color: #888;
  text-align: center;
  margin-top: 8px;
}
</style>
