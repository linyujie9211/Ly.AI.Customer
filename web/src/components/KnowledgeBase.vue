<template>
  <div class="kb-panel">
    <!-- 存储配置：本地 / ES -->
    <div class="section-card">
      <div class="storage-head">
        <h3 class="section-title">存储模式</h3>
        <div class="mode-switch">
          <label :class="['mode-option', storageConfig.mode === 'local' ? 'active' : '']">
            <input type="radio" value="local" v-model="storageConfig.mode" />
            本地存储
          </label>
          <label :class="['mode-option', storageConfig.mode === 'es' ? 'active' : '']">
            <input type="radio" value="es" v-model="storageConfig.mode" />
            Elasticsearch
          </label>
        </div>
      </div>

      <!-- 本地模式：保存路径 -->
      <div v-if="storageConfig.mode === 'local'" class="es-form">
        <div class="es-field grow">
          <label>本地知识库保存路径</label>
          <input v-model="storageConfig.local_path" class="form-control"
                 placeholder="例如 D:\data\knowledge_base，留空使用默认路径" />
        </div>
        <div class="es-actions">
          <button class="btn-secondary" :disabled="savingStorage" @click="saveStorage">
            {{ savingStorage ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>

      <!-- ES 模式：ES 连接配置 -->
      <div v-else class="es-form">
        <div class="es-field grow">
          <label>ES 地址</label>
          <input v-model="storageConfig.host" class="form-control" placeholder="例如 http://localhost:9200" />
        </div>
        <div class="es-field">
          <label>用户名</label>
          <input v-model="storageConfig.username" class="form-control" placeholder="无认证可留空" />
        </div>
        <div class="es-field">
          <label>密码</label>
          <input v-model="storageConfig.password" type="password" class="form-control" placeholder="无认证可留空" />
        </div>
        <div class="es-actions">
          <button class="btn-secondary" :disabled="savingStorage" @click="saveStorage">
            {{ savingStorage ? '保存中…' : '保存' }}
          </button>
          <button class="btn-secondary" :disabled="testing || savingStorage" @click="testEs">
            {{ testing ? '测试中…' : '测试连接' }}
          </button>
        </div>
      </div>
      <div v-if="storageResult" :class="['es-result', storageOk ? 'ok' : 'fail']">{{ storageResult }}</div>
    </div>

    <!-- 知识库列表 -->
    <div class="list-header">
      <p class="desc">配置本地文件夹路径，点击「生成知识库」解析文件并按当前存储模式保存（支持 txt / md / pdf / docx / xlsx / csv）。</p>
      <button class="add-btn" @click="showAddDialog">+ 新建知识库</button>
    </div>

    <div class="table-container">
      <table class="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>文件路径</th>
            <th>存储位置</th>
            <th>向量化模型</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="kb in kbs" :key="kb.id">
            <td>
              <div class="kb-name">
                <span class="icon">📚</span>
                <span>{{ kb.name }}</span>
              </div>
            </td>
            <td class="muted" :title="kb.folder_path">{{ kb.folder_path }}</td>
            <td class="muted" :title="kb.store_location">{{ kb.store_location }}</td>
            <td class="muted" :title="embedModelName(kb)">{{ embedModelName(kb) }}</td>
            <td>
              <span :class="['status-badge', kb.status]">{{ statusText(kb) }}</span>
              <div v-if="kb.status === 'error' && kb.error" class="error-tip" :title="kb.error">{{ kb.error }}</div>
            </td>
            <td>
              <div class="actions">
                <button class="btn-mini" :disabled="kb.status === 'building'" @click="buildKb(kb)">
                  {{ kb.status === 'building' ? '构建中…' : (kb.status === 'ready' ? '重新生成' : '生成知识库') }}
                </button>
                <button class="btn-icon" @click="editKb(kb)" title="编辑">✎</button>
                <button class="btn-icon btn-del" @click="deleteKb(kb)" title="删除">✕</button>
                <label class="switch">
                  <input type="checkbox" :checked="kb.enabled" @change="toggleKb(kb, $event.target.checked)">
                  <span class="slider"></span>
                </label>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="kbs.length === 0" class="empty">
        <p>暂无知识库，点击「+ 新建知识库」创建</p>
      </div>
    </div>

    <!-- 新建/编辑对话框 -->
    <div v-if="showDialog" class="dialog-overlay" @mousedown="onDialogMaskDown" @mouseup="onDialogMaskUp">
      <div class="dialog">
        <div class="dialog-header">
          <h2>{{ editingId ? '编辑知识库' : '新建知识库' }}</h2>
          <button class="btn-close" @click="closeDialog">✕</button>
        </div>
        <div class="dialog-body">
          <div class="form-group">
            <label class="required">知识库名称</label>
            <input v-model="form.name" class="form-control" placeholder="例如：产品手册" />
          </div>
          <div class="form-group">
            <label class="required">原始文件路径（服务器本地文件夹）</label>
            <div class="path-row">
              <input v-model="form.folder_path" class="form-control" readonly
                     placeholder="点击「浏览」选择服务器文件夹" />
              <button type="button" class="btn-browse" @click="openFolderPicker">浏览</button>
            </div>
            <div class="tip">
              <span class="tip-icon">ℹ</span>
              将递归解析该文件夹下所有 txt / md / pdf / docx / xlsx / csv 文件。
            </div>
          </div>
          <div class="form-group">
            <label>索引名 / 本地目录名（留空自动生成）</label>
            <input v-model="form.es_index" class="form-control" placeholder="留空则按知识库名称自动生成（如 kb_kouqiangzhishiku）" />
          </div>

          <div class="divider">向量化配置（可选，不选则仅关键词检索）</div>
          <div class="form-group">
            <label>向量化模型（Embedding 类型，从模型配置中选择）</label>
            <select v-model="form.embed_model_id" class="form-control">
              <option :value="null">不使用（仅关键词检索）</option>
              <option v-for="m in embedModels" :key="m.id" :value="m.id">
                {{ m.display_name || m.name }}（{{ m.model_id }}）
              </option>
            </select>
            <div class="tip" v-if="embedModels.length === 0">
              <span class="tip-icon">ℹ</span>
              尚无 Embedding 类型的模型，请先在「模型配置」中添加模型并将类型设为「Embedding」。
            </div>
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-save" @click="saveKb">{{ editingId ? '保存' : '创建' }}</button>
          <button class="btn-cancel" @click="closeDialog">取消</button>
        </div>
      </div>
    </div>

    <!-- 文件夹选择对话框 -->
    <div v-if="showFolderPicker" class="dialog-overlay" @mousedown="onPickerMaskDown" @mouseup="onPickerMaskUp">
      <div class="dialog folder-dialog">
        <div class="dialog-header">
          <h2>选择服务器文件夹</h2>
          <button class="btn-close" @click="closeFolderPicker">✕</button>
        </div>
        <div class="dialog-body">
          <div class="crumb-bar">
            <button type="button" class="btn-up" :disabled="!picker.path" @click="goUp">⬆ 上级</button>
            <span class="crumb-path" :title="picker.path">{{ picker.path || '此电脑' }}</span>
          </div>
          <div class="dir-list">
            <div v-if="pickerLoading" class="dir-empty">加载中…</div>
            <div v-else-if="picker.dirs.length === 0" class="dir-empty">该文件夹下没有子文件夹</div>
            <div v-else v-for="d in picker.dirs" :key="d" class="dir-item" @click="enterDir(d)">
              <span class="dir-icon">📁</span>
              <span class="dir-name">{{ dirName(d) }}</span>
            </div>
          </div>
          <div class="tip" style="margin-top: 10px;">
            <span class="tip-icon">ℹ</span>
            单击进入子文件夹，确认后点击「选择当前文件夹」。
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-save" :disabled="!picker.path" @click="chooseCurrent">选择当前文件夹</button>
          <button class="btn-cancel" @click="closeFolderPicker">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import api from '../api'
import { useMaskClose } from '../composables/useMaskClose'

// 遮罩关闭：mousedown/mouseup 都落在遮罩上才关闭，避免拖选文字误关弹窗
const { onMaskMouseDown: onDialogMaskDown, onMaskMouseUp: onDialogMaskUp } = useMaskClose(() => closeDialog())
const { onMaskMouseDown: onPickerMaskDown, onMaskMouseUp: onPickerMaskUp } = useMaskClose(() => closeFolderPicker())

const storageConfig = ref({ mode: 'local', local_path: '', host: '', username: '', password: '' })
const storageResult = ref('')
const storageOk = ref(false)
const savingStorage = ref(false)
const testing = ref(false)

const kbs = ref([])
const embedModels = ref([])
const showDialog = ref(false)
const editingId = ref(null)
const form = ref({})

// 文件夹选择控件
const showFolderPicker = ref(false)
const pickerLoading = ref(false)
const picker = ref({ path: '', parent: null, dirs: [] })

let pollTimer = null

onMounted(async () => {
  loadStorageConfig()
  await Promise.all([loadKbs(), loadEmbedModels()])
  startPolling()
})

onUnmounted(() => stopPolling())

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    if (kbs.value.some(k => k.status === 'building')) {
      loadKbs(true)
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function loadStorageConfig() {
  try {
    const res = await api.getStorageConfig()
    storageConfig.value = res.data
  } catch (e) {
    console.error('加载存储配置失败', e)
  }
}

async function saveStorage() {
  savingStorage.value = true
  storageResult.value = ''
  try {
    await api.saveStorageConfig(storageConfig.value)
    storageResult.value = '存储配置已保存'
    storageOk.value = true
    loadKbs(true) // 存储位置随模式变化，刷新列表
  } catch (e) {
    storageResult.value = '保存失败: ' + (e.response?.data?.detail || e.message)
    storageOk.value = false
  } finally {
    savingStorage.value = false
  }
}

async function testEs() {
  testing.value = true
  storageResult.value = ''
  try {
    const res = await api.testEsConfig(storageConfig.value)
    storageResult.value = `连接成功：集群 ${res.data.cluster_name || '-'}（ES ${res.data.es_version || '-'}）`
    storageOk.value = true
  } catch (e) {
    storageResult.value = '连接失败: ' + (e.response?.data?.detail || e.message)
    storageOk.value = false
  } finally {
    testing.value = false
  }
}

async function loadKbs(silent = false) {
  try {
    const res = await api.listKbs()
    kbs.value = res.data || []
  } catch (e) {
    if (!silent) console.error('加载知识库失败', e)
  }
}

async function loadEmbedModels() {
  try {
    const res = await api.listModels()
    // 只保留 Embedding 类型的模型
    embedModels.value = (res.data || []).filter(m => m.model_type === 'Embedding')
  } catch (e) {
    console.error('加载模型列表失败', e)
  }
}

function embedModelName(kb) {
  if (!kb.embed_model_id) return '仅关键词'
  const m = embedModels.value.find(x => x.id === kb.embed_model_id)
  return m ? (m.display_name || m.name) : '模型已删除（仅关键词）'
}

function statusText(kb) {
  const map = {
    idle: '未生成',
    building: '构建中…',
    ready: '已就绪',
    error: '构建失败'
  }
  return map[kb.status] || kb.status
}

function showAddDialog() {
  editingId.value = null
  form.value = {
    name: '', folder_path: '', es_index: '',
    embed_model_id: null
  }
  showDialog.value = true
}

function editKb(kb) {
  editingId.value = kb.id
  form.value = {
    name: kb.name,
    folder_path: kb.folder_path,
    es_index: kb.es_index,
    embed_model_id: kb.embed_model_id || null
  }
  showDialog.value = true
}

async function saveKb() {
  if (!form.value.name.trim() || !form.value.folder_path.trim()) {
    alert('请填写知识库名称和文件路径')
    return
  }
  try {
    if (editingId.value) {
      await api.updateKb(editingId.value, form.value)
    } else {
      await api.createKb(form.value)
    }
    closeDialog()
    loadKbs()
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function buildKb(kb) {
  try {
    await api.buildKb(kb.id)
    loadKbs(true)
  } catch (e) {
    alert('启动构建失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function deleteKb(kb) {
  if (!confirm(`确定删除知识库「${kb.name}」吗？对应的存储数据（${kb.store_location || kb.es_index}）也会被删除。`)) return
  try {
    await api.deleteKb(kb.id)
    loadKbs()
  } catch (e) {
    alert('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function toggleKb(kb, enabled) {
  try {
    await api.toggleKb(kb.id, enabled)
    kb.enabled = enabled
  } catch (e) {
    console.error('切换失败', e)
  }
}

function closeDialog() {
  showDialog.value = false
  editingId.value = null
}

// ---------- 文件夹选择控件 ----------
async function openFolderPicker() {
  showFolderPicker.value = true
  // 优先从当前已填路径开始浏览，无效则回到根
  await browseDir(form.value.folder_path || '', true)
}

async function browseDir(path, fallbackRoot = false) {
  pickerLoading.value = true
  try {
    const res = await api.listDirs(path)
    picker.value = res.data
  } catch (e) {
    if (fallbackRoot && path) {
      await browseDir('')
      return
    }
    alert('浏览目录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    pickerLoading.value = false
  }
}

function enterDir(d) {
  browseDir(d)
}

function goUp() {
  browseDir(picker.value.parent || '')
}

function dirName(d) {
  const parts = d.split(/[\\/]/).filter(Boolean)
  return parts[parts.length - 1] || d
}

function chooseCurrent() {
  if (!picker.value.path) return
  form.value.folder_path = picker.value.path
  closeFolderPicker()
}

function closeFolderPicker() {
  showFolderPicker.value = false
}
</script>

<style scoped>
.kb-panel {
  background: #FFFFFF;
}

.section-card {
  background: #F8FAFC;
  border: 1px solid #E5E5E5;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1F1F1F;
  margin-bottom: 10px;
}

.es-form {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  flex-wrap: wrap;
}

.es-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.es-field.grow {
  flex: 1;
  min-width: 200px;
}

.es-field label {
  font-size: 12px;
  color: #666;
}

.es-actions {
  display: flex;
  gap: 8px;
}

.btn-secondary {
  background: #FFFFFF;
  color: #3B82F6;
  border: 1px solid #3B82F6;
  padding: 7px 14px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.btn-secondary:hover {
  background: #3B82F6;
  color: #FFFFFF;
}

.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.es-result {
  margin-top: 10px;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
}

.es-result.ok {
  background: #ECFDF5;
  color: #047857;
}

.es-result.fail {
  background: #FEF2F2;
  color: #B91C1C;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.desc {
  font-size: 13px;
  color: #666;
}

.add-btn {
  background: #FFFFFF;
  color: #3B82F6;
  border: 1px solid #3B82F6;
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.add-btn:hover {
  background: #3B82F6;
  color: #FFFFFF;
}

.table-container {
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 8px;
  overflow-x: auto;
}

.table {
  width: 100%;
  min-width: 880px;
  border-collapse: collapse;
}

.table th {
  background: #F5F5F5;
  padding: 12px 16px;
  text-align: left;
  font-size: 13px;
  font-weight: 600;
  color: #1F1F1F;
  border-bottom: 1px solid #E5E5E5;
}

.table td {
  padding: 12px 16px;
  border-bottom: 1px solid #E5E5E5;
  font-size: 13px;
  color: #1F1F1F;
  vertical-align: top;
}

.kb-name {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.muted {
  color: #666;
  font-size: 12px;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

td:nth-child(3).muted,
th:nth-child(3) {
  max-width: 260px;
}

.storage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.storage-head .section-title {
  margin-bottom: 0;
}

.mode-switch {
  display: inline-flex;
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 8px;
  padding: 3px;
  gap: 4px;
}

.mode-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  color: #666;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s;
}

.mode-option input {
  display: none;
}

.mode-option.active {
  background: #3B82F6;
  color: #FFFFFF;
}

.status-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}

.status-badge.idle {
  background: #F5F5F5;
  color: #666;
}

.status-badge.building {
  background: #FEF3C7;
  color: #B45309;
}

.status-badge.ready {
  background: #ECFDF5;
  color: #047857;
}

.status-badge.error {
  background: #FEF2F2;
  color: #B91C1C;
}

.error-tip {
  font-size: 11px;
  color: #B91C1C;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 4px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-mini {
  background: #EBF3FE;
  color: #3B82F6;
  border: none;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-mini:hover {
  background: #3B82F6;
  color: #FFFFFF;
}

.btn-mini:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-icon {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  border-radius: 4px;
}

.btn-icon:hover {
  background: #E5E5E5;
}

.btn-del {
  color: #E74C3C;
}

.btn-del:hover {
  background: #FEE2E2;
}

.switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0; left: 0; right: 0; bottom: 0;
  background: #CCC;
  border-radius: 22px;
  transition: 0.2s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: 0.2s;
}

.switch input:checked + .slider {
  background: #3B82F6;
}

.switch input:checked + .slider:before {
  transform: translateX(18px);
}

.empty {
  text-align: center;
  padding: 40px;
  color: #999;
  font-size: 14px;
}

/* 对话框 */
.dialog-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: #FFFFFF;
  border-radius: 12px;
  width: 640px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #E5E5E5;
}

.dialog-header h2 {
  font-size: 18px;
  color: #1F1F1F;
}

.btn-close {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  font-size: 16px;
  cursor: pointer;
  color: #999;
  border-radius: 4px;
}

.btn-close:hover {
  background: #E5E5E5;
}

.dialog-body {
  padding: 20px;
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

.form-group label.required::after {
  content: " *";
  color: #E74C3C;
}

.form-control {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  font-size: 13px;
  background: #FFFFFF;
  color: #1F1F1F;
}

.form-control:focus {
  outline: none;
  border-color: #3B82F6;
}

.tip {
  background: #EBF3FE;
  color: #1E6FBA;
  font-size: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  margin-top: 8px;
  line-height: 1.4;
}

.tip-icon {
  margin-right: 4px;
}

/* 路径选择行 */
.path-row {
  display: flex;
  gap: 8px;
}

.path-row .form-control {
  flex: 1;
  background: #F8FAFC;
  color: #555;
  cursor: default;
}

.btn-browse {
  background: #FFFFFF;
  color: #3B82F6;
  border: 1px solid #3B82F6;
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.btn-browse:hover {
  background: #3B82F6;
  color: #FFFFFF;
}

/* 文件夹选择对话框 */
.folder-dialog {
  width: 560px;
}

.crumb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.btn-up {
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 12px;
  color: #1F1F1F;
  cursor: pointer;
  white-space: nowrap;
}

.btn-up:hover:not(:disabled) {
  background: #F5F5F5;
}

.btn-up:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.crumb-path {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: #1F1F1F;
  background: #F8FAFC;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 6px 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl;
  text-align: left;
}

.dir-list {
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  max-height: 320px;
  min-height: 180px;
  overflow-y: auto;
}

.dir-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  color: #1F1F1F;
  cursor: pointer;
  border-bottom: 1px solid #F0F0F0;
}

.dir-item:last-child {
  border-bottom: none;
}

.dir-item:hover {
  background: #EBF3FE;
}

.dir-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dir-empty {
  padding: 40px;
  text-align: center;
  color: #999;
  font-size: 13px;
}

.divider {
  font-size: 12px;
  color: #999;
  border-top: 1px dashed #E5E5E5;
  padding-top: 12px;
  margin: 16px 0;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px 20px;
  border-top: 1px solid #E5E5E5;
}

.btn-save {
  background: #3B82F6;
  color: #FFFFFF;
  border: none;
  padding: 8px 24px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.btn-save:hover {
  background: #2563EB;
}

.btn-cancel {
  background: #FFFFFF;
  color: #1F1F1F;
  border: 1px solid #E5E5E5;
  padding: 8px 24px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.btn-cancel:hover {
  background: #E5E5E5;
}
</style>
