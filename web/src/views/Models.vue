<template>
  <div class="models-panel">
    <p class="desc">配置 API key 添加更多可用模型，客服对话将使用此处启用的模型。</p>

    <button class="add-btn" @click="showAddDialog">+ 添加模型</button>

    <div class="table-container">
      <table class="table">
        <thead>
          <tr>
            <th>模型</th>
            <th>类型</th>
            <th>服务商</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in models" :key="m.id">
            <td>
              <div class="model-name">
                <span class="icon">◆</span>
                <span>{{ m.display_name || m.name }}</span>
                <span v-if="m.is_default" class="default-badge">默认</span>
              </div>
            </td>
            <td>
              <span :class="['type-badge', typeClass(m.model_type)]">{{ typeLabel(m.model_type) }}</span>
            </td>
            <td class="provider">{{ m.provider || '自定义' }}</td>
            <td>
              <div class="actions">
                <button v-if="!m.is_default" class="btn-link" @click="setDefault(m)" title="设为该类型默认模型">设默认</button>
                <button class="btn-icon" @click="duplicateModel(m.id)" title="复制">⧉</button>
                <button class="btn-icon" @click="editModel(m.id)" title="编辑">✎</button>
                <button class="btn-icon btn-del" @click="deleteModel(m.id, m.name)" title="删除">✕</button>
                <label class="switch">
                  <input type="checkbox" :checked="!!m.enabled" @change="toggleModel(m.id, $event.target.checked)">
                  <span class="slider"></span>
                </label>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="models.length === 0" class="empty">
      <p>暂无模型，点击「+ 添加模型」添加</p>
    </div>

    <!-- 添加/编辑对话框 -->
    <div v-if="showDialog" class="dialog-overlay" @mousedown="onMaskMouseDown" @mouseup="onMaskMouseUp">
      <div class="dialog">
        <div class="dialog-header">
          <h2>{{ editingId ? '编辑模型' : '添加模型' }}</h2>
          <button class="btn-close" @click="closeDialog">✕</button>
        </div>

        <div class="dialog-body">
          <div class="form-group">
            <label class="required">模型类型</label>
            <select v-model="form.model_type" class="form-control">
              <option v-for="t in MODEL_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </div>

          <div class="form-group">
            <label class="required">API 格式</label>
            <select v-model="form.api_format" class="form-control">
              <option value="OpenAI Chat Completions 格式">OpenAI Chat Completions 格式</option>
              <option value="Anthropic 格式">Anthropic 格式</option>
              <option value="自定义格式">自定义格式</option>
            </select>
          </div>

          <div class="form-group">
            <label class="required">自定义请求地址</label>
            <input v-model="form.base_url" class="form-control" placeholder="例如 https://api.openai.com/v1" />
            <div class="tip">
              <span class="tip-icon">ℹ</span>
              请填写兼容 OpenAI API 的服务端点地址，不要以斜杠结尾。
              /chat/completions 将会被补充到你所填写的地址末尾。
            </div>
          </div>

          <div class="form-group">
            <label class="required">模型 ID</label>
            <input v-model="form.model_id" class="form-control" placeholder="输入模型 ID" />
          </div>

          <div class="form-group">
            <label class="required">API 密钥</label>
            <input v-model="form.api_key" type="password" class="form-control" placeholder="输入 API 密钥" />
          </div>

          <div class="form-group">
            <label class="required">模型名称</label>
            <input v-model="form.name" class="form-control" placeholder="请输入模型名称" />
          </div>

          <div class="form-group">
            <label>启用</label>
            <label class="switch">
              <input type="checkbox" v-model="form.enabled">
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <div class="dialog-footer">
          <button class="btn-save" @click="saveModel">{{ editingId ? '保存' : '添加模型' }}</button>
          <button class="btn-cancel" @click="closeDialog">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'
import { useMaskClose } from '../composables/useMaskClose'

// 遮罩关闭：mousedown/mouseup 都落在遮罩上才关闭，避免拖选文字误关弹窗
const { onMaskMouseDown, onMaskMouseUp } = useMaskClose(() => closeDialog())

const models = ref([])
const showDialog = ref(false)
const editingId = ref(null)

// 模型类型（value 与后端约定存储中文标签本身）
const MODEL_TYPES = [
  { value: '对话', label: '对话（Chat）' },
  { value: '图文理解', label: '图文理解（Vision）' },
  { value: 'Embedding', label: '文本向量化（Embedding）' },
  { value: '重排序', label: '重排序（Rerank）' },
  { value: '文生图', label: '文生图（Text to Image）' },
  { value: '图生图', label: '图生图（Image to Image）' },
  { value: '图像编辑', label: '图像编辑（Image Edit）' },
  { value: '文生视频', label: '文生视频（Text to Video）' },
  { value: '图生视频', label: '图生视频（Image to Video）' },
  { value: '语音识别', label: '语音识别（ASR）' },
  { value: '语音合成', label: '语音合成（TTS）' },
  { value: '实时语音', label: '实时语音（Realtime）' },
  { value: '内容审核', label: '内容审核（Moderation）' }
]

function typeLabel(t) {
  const item = MODEL_TYPES.find(x => x.value === t)
  return item ? item.value : (t || '对话')
}

function typeClass(t) {
  const map = {
    '对话': 't-chat',
    '图文理解': 't-vision',
    'Embedding': 't-embedding',
    '重排序': 't-rerank',
    '文生图': 't-image',
    '图生图': 't-image',
    '图像编辑': 't-image',
    '文生视频': 't-video',
    '图生视频': 't-video',
    '语音识别': 't-audio',
    '语音合成': 't-audio',
    '实时语音': 't-audio',
    '内容审核': 't-moderation'
  }
  return map[t] || 't-chat'
}

const form = ref({
  name: '',
  model_type: '对话',
  api_format: 'OpenAI Chat Completions 格式',
  base_url: '',
  model_id: '',
  api_key: '',
  model_family: '默认',
  display_name: '',
  context_input: 184000,
  context_output: 16000,
  tool_calls: 200,
  provider: '自定义',
  enabled: true,
  is_builtin: false
})

onMounted(() => {
  loadModels()
})

async function loadModels() {
  try {
    const res = await api.listModels()
    models.value = res.data || []
  } catch (e) {
    console.error('加载模型失败', e)
    models.value = []
  }
}

function showAddDialog() {
  editingId.value = null
  form.value = {
    name: '', model_type: '对话', api_format: 'OpenAI Chat Completions 格式', base_url: '',
    model_id: '', api_key: '', model_family: '默认',
    display_name: '', context_input: 184000, context_output: 16000,
    tool_calls: 200, provider: '自定义', enabled: true, is_builtin: false
  }
  showDialog.value = true
}

async function editModel(id) {
  try {
    const res = await api.getModel(id)
    form.value = { ...res.data }
    editingId.value = id
    showDialog.value = true
  } catch (e) {
    console.error('加载模型详情失败', e)
  }
}

async function deleteModel(id, name) {
  if (!confirm(`确定删除「${name}」吗？`)) return
  try {
    await api.deleteModel(id)
    loadModels()
  } catch (e) {
    console.error('删除失败', e)
  }
}

async function duplicateModel(id) {
  try {
    await api.duplicateModel(id)
    loadModels()
  } catch (e) {
    alert('复制失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function setDefault(m) {
  try {
    await api.setDefaultModel(m.id)
    loadModels()
  } catch (e) {
    alert('设置默认失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function toggleModel(id, enabled) {
  try {
    await api.toggleModel(id, enabled)
    const m = models.value.find(x => x.id === id)
    if (m) m.enabled = enabled ? 1 : 0
  } catch (e) {
    console.error('切换失败', e)
  }
}

async function saveModel() {
  if (!form.value.name || !form.value.model_id) {
    alert('请输入模型名称和模型 ID')
    return
  }
  try {
    if (editingId.value) {
      await api.updateModel(editingId.value, form.value)
    } else {
      await api.createModel(form.value)
    }
    closeDialog()
    loadModels()
  } catch (e) {
    alert('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

function closeDialog() {
  showDialog.value = false
  editingId.value = null
}
</script>

<style scoped>
.models-panel {
  background: #FFFFFF;
}

.desc {
  font-size: 13px;
  color: #666;
  margin-bottom: 16px;
}

.add-btn {
  background: #FFFFFF;
  color: #3B82F6;
  border: 1px solid #3B82F6;
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  margin-bottom: 16px;
  transition: all 0.15s;
}

.add-btn:hover {
  background: #3B82F6;
  color: #FFFFFF;
}

.table-container {
  background: #FFFFFF;
  border: 1px solid #E5E5E5;
  border-radius: 8px;
  overflow: hidden;
}

.table {
  width: 100%;
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
}

.model-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 文字链接按钮（设默认等），同 LyTools 全局风格 */
.btn-link {
  border: none;
  background: transparent;
  color: #3B82F6;
  font-size: 13px;
  cursor: pointer;
  padding: 2px 4px;
  white-space: nowrap;
}

.btn-link:hover { text-decoration: underline; }

.default-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  background: #FFF7E6;
  color: #D48806;
  border: 1px solid #FFD591;
  white-space: nowrap;
}

.icon {
  color: #3B82F6;
  font-size: 14px;
}

.type-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}

.t-chat { background: #EBF3FE; color: #1D4ED8; }
.t-vision { background: #F3E8FF; color: #7C3AED; }
.t-embedding { background: #ECFDF5; color: #047857; }
.t-rerank { background: #CCFBF1; color: #0F766E; }
.t-image { background: #FEF3C7; color: #B45309; }
.t-video { background: #FCE7F3; color: #BE185D; }
.t-audio { background: #E0E7FF; color: #4338CA; }
.t-moderation { background: #FEE2E2; color: #B91C1C; }

.provider {
  color: #666;
  font-size: 12px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
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
  display: inline-flex;
  align-items: center;
  justify-content: center;
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

/* 开关 */
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

.switch.small {
  width: 36px;
  height: 20px;
}

.switch.small .slider:before {
  height: 14px;
  width: 14px;
}

.switch.small input:checked + .slider:before {
  transform: translateX(16px);
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

.switch-label {
  font-size: 12px;
  color: #666;
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
