<template>
  <div class="plugins-manage">
    <p class="desc">
      插件 = 知识包（提示词）+ 可选工具（Python）。启用后智能客服会自动识别并使用；
      导入的插件默认禁用，请先审查代码并测试通过后再启用。
    </p>

    <div class="list-toolbar">
      <input
        v-model="keyword"
        class="filter-input"
        placeholder="筛选插件：名称 / 描述 / 工具关键字"
      >
      <button class="btn-plain" :disabled="importing" @click="pickImport">
        {{ importing ? '导入中…' : '上传插件（zip）' }}
      </button>
      <input ref="importInput" type="file" accept=".zip" style="display:none" @change="onImportFile">
    </div>

    <div class="table-container">
      <table class="table">
        <thead>
          <tr>
            <th>插件</th>
            <th>描述</th>
            <th>工具</th>
            <th>创建时间</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in pagedPlugins" :key="p.id">
            <td>
              <div class="cell-name">
                <span class="plugin-name">{{ p.name }}</span>
                <span v-if="p.builtin" class="badge builtin">内置</span>
                <template v-else>
                  <span class="badge version">v{{ p.version }}</span>
                  <span v-if="p.source === 'imported'" class="badge imported">导入</span>
                  <span v-else-if="p.source === 'manual'" class="badge manual">手动</span>
                </template>
                <span v-if="p.load_error" class="badge err" :title="p.load_error">加载失败</span>
              </div>
            </td>
            <td class="cell-desc" :title="p.description">{{ p.description || '（无描述）' }}</td>
            <td class="cell-tools">
              <span v-if="p.tools && p.tools.length" :title="p.tools.join('、')">{{ p.tools.length }} 个工具</span>
              <span v-else-if="p.has_tools" class="muted" title="插件含 tools.py，禁用状态下未加载工具明细">有工具</span>
              <span v-else class="muted">纯知识包</span>
            </td>
            <td class="cell-time">{{ p.created_at }}</td>
            <td>
              <label v-if="!p.builtin" class="switch" :title="p.enabled ? '点击禁用' : '点击启用'">
                <input type="checkbox" :checked="p.enabled" @change="toggle(p, $event.target.checked)">
                <span class="slider"></span>
              </label>
              <span v-else class="muted">始终启用</span>
            </td>
            <td>
              <div v-if="!p.builtin" class="cell-actions">
                <button class="btn-link" @click="openReview(p)">查看</button>
                <button v-if="p.has_tools" class="btn-link" @click="openReview(p)">测试</button>
                <button class="btn-link" @click="download(p)">下载</button>
                <button class="btn-link danger" @click="removePlugin(p)">删除</button>
              </div>
              <span v-else class="muted">—</span>
            </td>
          </tr>
          <tr v-if="!pagedPlugins.length">
            <td colspan="6" class="empty-cell">
              {{ keyword.trim() ? `没有匹配「${keyword.trim()}」的插件` : '暂无插件。可上传插件 zip 包导入。' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 分页 -->
    <div v-if="filteredPlugins.length" class="pager">
      <span class="pager-info">共 {{ filteredPlugins.length }} 条</span>
      <select v-model.number="pageSize" class="pager-size">
        <option :value="10">10 条/页</option>
        <option :value="20">20 条/页</option>
        <option :value="50">50 条/页</option>
      </select>
      <button class="pager-btn" :disabled="page <= 1" @click="page--">上一页</button>
      <span class="pager-info">{{ page }} / {{ totalPages }}</span>
      <button class="pager-btn" :disabled="page >= totalPages" @click="page++">下一页</button>
    </div>

    <!-- 审查 + 测试 弹窗 -->
    <div v-if="dialogPlugin" class="dialog-overlay" @mousedown="onMaskMouseDown" @mouseup="onMaskMouseUp">
      <div class="dialog wide">
        <div class="dialog-header">
          <h2>{{ dialogTitle }}</h2>
          <button class="btn-close" @click="closeDialog">✕</button>
        </div>
        <div class="dialog-body">
          <!-- 文件审查 -->
          <div class="file-tabs">
            <button
              v-for="(_, fname) in dialogFiles" :key="fname"
              :class="['tab', { active: dialogActiveFile === fname }]"
              @click="dialogActiveFile = fname"
            >{{ fname }}</button>
          </div>
          <pre class="code-view">{{ dialogFiles[dialogActiveFile] || '（空）' }}</pre>

          <!-- 工具测试 -->
          <div class="test-section">
            <h3 class="test-title">工具测试</h3>
            <template v-if="!dialogPlugin.has_tools">
              <p class="muted">该插件只有知识包（无工具），启用后智能客服会在匹配场景自动按其提示词工作。</p>
            </template>
            <template v-else>
              <div v-if="inspectError" class="error-text">
                {{ inspectError }}
                <button class="btn-link" @click="loadTools">重试</button>
              </div>
              <p v-else-if="inspecting" class="muted">正在加载工具定义…</p>
              <template v-else-if="toolDefs.length">
                <div class="arg-row">
                  <label class="arg-label">选择工具</label>
                  <select v-model="selectedToolName" class="arg-input" @change="onToolChange">
                    <option v-for="t in toolDefs" :key="t.name" :value="t.name">
                      {{ t.label }}（{{ t.name }}）
                    </option>
                  </select>
                </div>
                <template v-if="selectedToolDef">
                  <p class="tool-desc">{{ selectedToolDef.description }}</p>
                  <p v-if="!selectedToolDef.readonly" class="warn-text">
                    ⚠ 该工具为写操作（readonly=false），测试时会真实执行，请注意影响范围。
                  </p>
                  <div
                    v-for="(schema, pname) in (selectedToolDef.parameters.properties || {})"
                    :key="pname" class="arg-row"
                  >
                    <label class="arg-label">
                      {{ pname }}<span v-if="isRequired(pname)" class="req">*</span>
                      <span class="arg-type">{{ schema.type || 'string' }}</span>
                    </label>
                    <textarea
                      v-if="schema.type === 'array' || schema.type === 'object'"
                      v-model="argValues[pname]" rows="2" class="arg-input"
                      :placeholder="schema.description || 'JSON 格式'"
                    ></textarea>
                    <input
                      v-else-if="schema.type === 'number' || schema.type === 'integer'"
                      v-model="argValues[pname]" type="number" class="arg-input"
                      :placeholder="schema.description || ''"
                    >
                    <select v-else-if="schema.type === 'boolean'" v-model="argValues[pname]" class="arg-input">
                      <option :value="false">false</option>
                      <option :value="true">true</option>
                    </select>
                    <input
                      v-else v-model="argValues[pname]" class="arg-input"
                      :placeholder="schema.description || ''"
                    >
                    <p v-if="propErrors[pname]" class="error-text">{{ propErrors[pname] }}</p>
                  </div>
                  <div class="run-row">
                    <button class="btn-main" :disabled="testing" @click="runTest">
                      {{ testing ? '执行中…' : '运行测试' }}
                    </button>
                    <span v-if="testResult && testResult.ms != null" class="run-ms">耗时 {{ testResult.ms }}ms</span>
                  </div>
                  <div v-if="testResult" :class="['result-box', testResult.ok ? 'ok' : 'fail']">
                    <p class="result-head">{{ testResult.ok ? '✓ 执行成功' : '✗ 执行失败' }}</p>
                    <pre class="result-body">{{ fmtPayload(testResult.result) }}</pre>
                  </div>
                </template>
              </template>
              <p v-else class="muted">
                未发现可测试的工具（tools.py 可能未注册任何 @tool）
                <button class="btn-link" @click="loadTools">重新加载</button>
              </p>
            </template>
          </div>
        </div>
        <div class="dialog-footer">
          <button
            v-if="!dialogPlugin.enabled" class="btn-main" :disabled="enabling"
            @click="enableFromDialog"
          >{{ enabling ? '启用中…' : (testResult && testResult.ok ? '测试通过，启用插件' : '启用插件') }}</button>
          <button v-if="!dialogPlugin.enabled" class="btn-plain danger" @click="deleteFromDialog">删除</button>
          <button class="btn-plain" @click="closeDialog">关闭</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../api'
import { useMaskClose } from '../composables/useMaskClose'

// 遮罩关闭：mousedown/mouseup 都落在遮罩上才关闭，避免拖选文字误关弹窗
const { onMaskMouseDown, onMaskMouseUp } = useMaskClose(() => closeDialog())

const plugins = ref([])

// 筛选 + 分页（后端已把内置插件排前，前端兜底再排一次）
const keyword = ref('')
const page = ref(1)
const pageSize = ref(10)
const sortedPlugins = computed(() => {
  const arr = [...plugins.value]
  arr.sort((a, b) => (b.builtin ? 1 : 0) - (a.builtin ? 1 : 0))
  return arr
})
const filteredPlugins = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return sortedPlugins.value
  return sortedPlugins.value.filter(p => {
    const hay = [p.id, p.name, p.description, (p.tools || []).join(' ')].join(' ').toLowerCase()
    return hay.includes(kw)
  })
})
const totalPages = computed(() => Math.max(1, Math.ceil(filteredPlugins.value.length / pageSize.value)))
const pagedPlugins = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredPlugins.value.slice(start, start + pageSize.value)
})
watch([keyword, pageSize], () => { page.value = 1 })
watch(totalPages, (tp) => { if (page.value > tp) page.value = tp })

// 上传导入
const importInput = ref(null)
const importing = ref(false)

// 审查 + 测试弹窗
const dialogPlugin = ref(null)
const dialogFiles = ref({})
const dialogActiveFile = ref('')
const enabling = ref(false)
const toolDefs = ref([])
const inspecting = ref(false)
const inspectError = ref('')
const selectedToolName = ref('')
const argValues = ref({})
const propErrors = ref({})
const testing = ref(false)
const testResult = ref(null)

const dialogTitle = computed(() => {
  if (!dialogPlugin.value) return ''
  const p = dialogPlugin.value
  if (!p.enabled) return `审查插件：${p.name}（当前禁用）`
  return `插件：${p.name}`
})

const selectedToolDef = computed(() =>
  toolDefs.value.find(t => t.name === selectedToolName.value) || null)

function isRequired(pname) {
  const req = selectedToolDef.value?.parameters?.required || []
  return req.includes(pname)
}

function fmtPayload(payload) {
  if (payload == null) return '（无输出）'
  let obj = payload
  if (typeof obj === 'string') {
    const s = obj.trim()
    if ((s.startsWith('{') && s.endsWith('}')) || (s.startsWith('[') && s.endsWith(']'))) {
      try { obj = JSON.parse(s) } catch { return payload }
    } else {
      return payload
    }
  }
  try { return JSON.stringify(obj, null, 2) } catch { return String(payload) }
}

// ---------- 数据加载 ----------
async function refresh() {
  const r = await api.listPlugins()
  plugins.value = r.data
}

// ---------- 上传导入 / 下载 ----------
function pickImport() {
  importInput.value?.click()
}

async function onImportFile(e) {
  const file = e.target.files[0]
  e.target.value = ''
  if (!file) return
  importing.value = true
  try {
    const r = await api.importPlugin(file)
    await refresh()
    openReview(r.data, r.data.files) // 导入后默认禁用，直接打开审查+测试
  } catch (err) {
    alert(err.response?.data?.detail || '导入失败')
  } finally {
    importing.value = false
  }
}

async function download(p) {
  try {
    const r = await api.exportPlugin(p.id)
    const url = URL.createObjectURL(new Blob([r.data], { type: 'application/zip' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${p.id}.zip`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(e.response?.data?.detail || '下载失败')
  }
}

// ---------- 审查 + 测试弹窗 ----------
async function openReview(p, files) {
  dialogPlugin.value = p
  testResult.value = null
  toolDefs.value = []
  selectedToolName.value = ''
  argValues.value = {}
  propErrors.value = {}
  inspectError.value = ''
  if (files && Object.keys(files).length) {
    dialogFiles.value = files
  } else {
    try {
      const r = await api.getPluginFiles(p.id)
      dialogFiles.value = r.data
    } catch {
      dialogFiles.value = {}
    }
  }
  dialogActiveFile.value = dialogFiles.value['tools.py']
    ? 'tools.py'
    : Object.keys(dialogFiles.value)[0] || ''
  if (p.has_tools) await loadTools()
}

function closeDialog() {
  dialogPlugin.value = null
}

async function loadTools() {
  if (!dialogPlugin.value?.has_tools) return
  inspecting.value = true
  inspectError.value = ''
  try {
    const r = await api.inspectPluginTools(dialogPlugin.value.id)
    toolDefs.value = r.data.tools || []
    selectedToolName.value = toolDefs.value[0]?.name || ''
    onToolChange()
  } catch (e) {
    toolDefs.value = []
    inspectError.value = e.response?.data?.detail || '工具加载失败（tools.py 可能存在运行时错误）'
  } finally {
    inspecting.value = false
  }
}

function onToolChange() {
  propErrors.value = {}
  testResult.value = null
  const props = selectedToolDef.value?.parameters?.properties || {}
  const v = {}
  for (const [name, schema] of Object.entries(props)) {
    const t = schema.type || 'string'
    if (t === 'boolean') v[name] = false
    else if (t === 'number' || t === 'integer') v[name] = null
    else if (t === 'array') v[name] = '[]'
    else if (t === 'object') v[name] = '{}'
    else v[name] = ''
  }
  argValues.value = v
}

function buildArgs() {
  const props = selectedToolDef.value?.parameters?.properties || {}
  const required = selectedToolDef.value?.parameters?.required || []
  propErrors.value = {}
  const args = {}
  for (const [name, schema] of Object.entries(props)) {
    const val = argValues.value[name]
    const t = schema.type || 'string'
    if (t === 'number' || t === 'integer') {
      if (val === null || val === undefined || val === '') {
        if (required.includes(name)) { propErrors.value[name] = '必填参数'; return null }
        continue
      }
      const n = Number(val)
      if (Number.isNaN(n)) { propErrors.value[name] = '请输入数字'; return null }
      args[name] = n
    } else if (t === 'array' || t === 'object') {
      const fallback = t === 'array' ? '[]' : '{}'
      try {
        const parsed = JSON.parse((val ?? '').trim() || fallback)
        args[name] = parsed
      } catch {
        propErrors.value[name] = 'JSON 格式不合法'; return null
      }
    } else if (t === 'boolean') {
      args[name] = !!val
    } else {
      if (!val) {
        if (required.includes(name)) { propErrors.value[name] = '必填参数'; return null }
        continue
      }
      args[name] = val
    }
  }
  return args
}

async function runTest() {
  if (!dialogPlugin.value || !selectedToolName.value) return
  const args = buildArgs()
  if (args === null) return
  testing.value = true
  testResult.value = null
  const t0 = Date.now()
  try {
    const r = await api.testPluginTool(dialogPlugin.value.id, selectedToolName.value, args)
    testResult.value = { ok: r.data.ok, result: r.data.result, ms: Date.now() - t0 }
  } catch (e) {
    testResult.value = {
      ok: false,
      result: e.response?.data?.detail || '执行失败',
      ms: Date.now() - t0
    }
  } finally {
    testing.value = false
  }
}

async function enableFromDialog() {
  if (!dialogPlugin.value) return
  enabling.value = true
  try {
    const r = await api.togglePlugin(dialogPlugin.value.id, true)
    dialogPlugin.value = r.data
    await refresh()
  } catch (e) {
    alert(e.response?.data?.detail || '启用失败（工具加载出错，请检查 tools.py）')
  } finally {
    enabling.value = false
  }
}

async function deleteFromDialog() {
  if (!dialogPlugin.value) return
  if (!confirm(`确定删除插件「${dialogPlugin.value.name}」？该操作不可恢复。`)) return
  try {
    await api.deletePlugin(dialogPlugin.value.id)
    closeDialog()
    await refresh()
  } catch (e) {
    alert(e.response?.data?.detail || '删除失败')
  }
}

// ---------- 列表操作 ----------
async function toggle(p, enabled) {
  try {
    await api.togglePlugin(p.id, enabled)
  } catch (e) {
    alert(e.response?.data?.detail || '操作失败')
  }
  await refresh()
}

async function removePlugin(p) {
  if (!confirm(`确定删除插件「${p.name}」？该操作不可恢复。`)) return
  try {
    await api.deletePlugin(p.id)
    await refresh()
  } catch (e) {
    alert(e.response?.data?.detail || '删除失败')
  }
}

onMounted(() => {
  refresh()
})
</script>

<style scoped>
.desc { color: #666; font-size: 13px; margin: 0 0 14px; line-height: 1.6; }
.muted { color: #999; font-size: 13px; }
.error-text { color: #d03050; font-size: 12px; margin: 4px 0 0; }
.warn-text { color: #d46b08; font-size: 12px; margin: 4px 0; }

.list-toolbar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 12px;
}
.filter-input {
  flex: 1; max-width: 320px; padding: 8px 12px; border: 1px solid #E5E5E5;
  border-radius: 8px; font-size: 13px; font-family: inherit; outline: none;
}
.filter-input:focus { border-color: #3B82F6; }

.btn-main {
  padding: 8px 16px; background: #3B82F6; color: #fff; border: none;
  border-radius: 8px; font-size: 13px; cursor: pointer; font-family: inherit;
  white-space: nowrap; transition: background 0.15s;
}
.btn-main:disabled { background: #A5C4F7; cursor: not-allowed; }
.btn-main:hover:not(:disabled) { background: #2563EB; }
.btn-plain {
  padding: 8px 16px; background: #fff; color: #444; border: 1px solid #E5E5E5;
  border-radius: 8px; font-size: 13px; cursor: pointer; font-family: inherit;
  white-space: nowrap; transition: background 0.15s;
}
.btn-plain:hover:not(:disabled) { background: #F5F5F5; }
.btn-plain:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-plain.danger { color: #EF4444; border-color: #FECACA; }
.btn-plain.danger:hover { background: #FEF2F2; }
.btn-link {
  background: transparent; border: none; color: #3B82F6; font-size: 13px;
  cursor: pointer; padding: 2px 4px; font-family: inherit;
}
.btn-link:hover { text-decoration: underline; }
.btn-link.danger { color: #EF4444; }

/* 表格 */
.table-container {
  background: #fff; border: 1px solid #E5E5E5; border-radius: 10px; overflow: auto;
}
.table { width: 100%; border-collapse: collapse; }
.table th {
  background: #FAFAFA; padding: 10px 14px; text-align: left;
  font-size: 13px; font-weight: 600; color: #1F1F1F; border-bottom: 1px solid #E5E5E5;
  white-space: nowrap;
}
.table td {
  padding: 10px 14px; border-bottom: 1px solid #F0F0F0;
  font-size: 13px; color: #1F1F1F; vertical-align: middle;
}
.table tr:last-child td { border-bottom: none; }
.cell-name { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.cell-desc {
  max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #555;
}
.cell-tools { color: #555; white-space: nowrap; }
.cell-time { color: #999; font-size: 12px; white-space: nowrap; }
.cell-actions { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.empty-cell { text-align: center; color: #999; padding: 36px 16px !important; }

/* 徽标 */
.plugin-name { font-size: 13px; font-weight: 600; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 10px; background: #F0F1F2; color: #666; }
.badge.version { background: #EBF3FE; color: #3B82F6; }
.badge.imported { background: #E8F7FF; color: #0E7DD1; }
.badge.manual { background: #F3EEFF; color: #7C3AED; }
.badge.err { background: #FFF1F0; color: #CF1322; }
.badge.builtin { background: #E8F3FF; color: #0958D9; }

/* 开关 */
.switch { position: relative; display: inline-block; width: 36px; height: 20px; }
.switch input { opacity: 0; width: 0; height: 0; }
.slider {
  position: absolute; cursor: pointer; inset: 0; background: #D4D4D4;
  border-radius: 999px; transition: 0.2s;
}
.slider::before {
  content: ''; position: absolute; height: 16px; width: 16px; left: 2px; top: 2px;
  background: #fff; border-radius: 50%; transition: 0.2s; box-shadow: 0 1px 2px rgba(0,0,0,0.2);
}
.switch input:checked + .slider { background: #3B82F6; }
.switch input:checked + .slider::before { transform: translateX(16px); }

/* 分页 */
.pager {
  display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 12px;
}
.pager-info { color: #999; font-size: 12px; }
.pager-size {
  border: 1px solid #E5E5E5; border-radius: 6px; padding: 4px 8px; font-size: 12px;
  font-family: inherit; background: #fff; cursor: pointer;
}
.pager-btn {
  border: 1px solid #E5E5E5; background: #fff; border-radius: 6px; padding: 4px 12px;
  font-size: 12px; cursor: pointer; font-family: inherit;
}
.pager-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.pager-btn:hover:not(:disabled) { background: #F5F5F5; }

/* 弹窗（设置弹窗 z-index 960，这里更高一层） */
.dialog-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.45); display: flex;
  align-items: center; justify-content: center; z-index: 1000;
}
.dialog {
  background: #fff; border-radius: 12px; width: 520px; max-width: 92vw; max-height: 85vh;
  display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,0.2);
}
.dialog.wide { width: 780px; }
.dialog-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 20px; border-bottom: 1px solid #F0F0F0;
}
.dialog-header h2 { font-size: 15px; margin: 0; color: #1F1F1F; }
.btn-close {
  width: 28px; height: 28px; border: none; background: transparent; font-size: 15px;
  cursor: pointer; color: #666; border-radius: 6px;
}
.btn-close:hover { background: #F0F0F0; color: #1F1F1F; }
.dialog-body { padding: 16px 20px; overflow-y: auto; }
.dialog-footer {
  padding: 12px 20px; border-top: 1px solid #F0F0F0;
  display: flex; gap: 10px; justify-content: flex-end;
}

/* 文件审查 */
.file-tabs { display: flex; gap: 6px; margin-bottom: 10px; }
.tab {
  padding: 4px 12px; border: 1px solid #E5E5E5; border-radius: 6px; background: #fff;
  cursor: pointer; font-size: 12px; font-family: inherit; color: #444;
}
.tab.active { background: #3B82F6; color: #fff; border-color: #3B82F6; }
.code-view {
  background: #F7F8FA; border: 1px solid #EBEDF0; border-radius: 8px; padding: 12px;
  font-size: 12px; line-height: 1.6; overflow: auto; white-space: pre-wrap;
  word-break: break-all; max-height: 30vh; margin: 0;
}

/* 测试区 / 表单 */
.test-section { margin-top: 16px; border-top: 1px dashed #E5E6EB; padding-top: 12px; }
.test-title { font-size: 13px; font-weight: 600; margin: 0 0 10px; }
.tool-desc { color: #555; font-size: 12px; margin: 6px 0; }
.arg-row { margin-bottom: 10px; }
.arg-label { display: block; font-size: 12px; color: #666; margin-bottom: 4px; }
.arg-type { color: #BBB; margin-left: 6px; }
.req { color: #EF4444; margin-left: 2px; }
.arg-input {
  width: 100%; box-sizing: border-box; padding: 7px 10px; border: 1px solid #E5E5E5;
  border-radius: 8px; font-size: 13px; font-family: inherit; resize: vertical; outline: none;
}
.arg-input:focus { border-color: #3B82F6; }
.run-row { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
.run-ms { color: #999; font-size: 12px; }
.result-box { margin-top: 10px; border-radius: 8px; padding: 10px 12px; }
.result-box.ok { background: #F6FFED; border: 1px solid #B7EB8F; }
.result-box.fail { background: #FFF1F0; border: 1px solid #FFA39E; }
.result-head { font-size: 13px; font-weight: 600; margin: 0 0 6px; }
.result-box.ok .result-head { color: #389E0D; }
.result-box.fail .result-head { color: #CF1322; }
.result-body {
  margin: 0; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-all;
  max-height: 26vh; overflow-y: auto;
}
</style>
