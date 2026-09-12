import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000
})

export default {
  // 用户认证
  login: (data) => api.post('/auth/login', data),
  register: (data) => api.post('/auth/register', data),

  // 模型管理
  listModels: () => api.get('/models'),
  getModel: (id) => api.get('/models/' + id),
  createModel: (data) => api.post('/models', data),
  updateModel: (id, data) => api.put('/models/' + id, data),
  deleteModel: (id) => api.delete('/models/' + id),
  toggleModel: (id, enabled) => api.patch('/models/' + id + '/toggle', null, { params: { enabled } }),
  duplicateModel: (id) => api.post('/models/' + id + '/duplicate'),
  setDefaultModel: (id) => api.post('/models/' + id + '/default'),

  // 知识库存储配置（本地 / ES 模式）
  getStorageConfig: () => api.get('/kb/storage-config'),
  saveStorageConfig: (data) => api.post('/kb/storage-config', data),

  // ES 连接配置
  getEsConfig: () => api.get('/kb/es-config'),
  saveEsConfig: (data) => api.post('/kb/es-config', data),
  testEsConfig: (data) => api.post('/kb/es-config/test', data, { timeout: 15000 }),

  // 知识库管理
  listKbs: () => api.get('/kb'),
  createKb: (data) => api.post('/kb', data),
  updateKb: (id, data) => api.put('/kb/' + id, data),
  deleteKb: (id) => api.delete('/kb/' + id),
  toggleKb: (id, enabled) => api.patch('/kb/' + id + '/toggle', null, { params: { enabled } }),
  buildKb: (id) => api.post('/kb/' + id + '/build', null, { timeout: 30000 }),

  // 服务器目录浏览（文件夹选择控件）
  listDirs: (path) => api.get('/fs/dirs', { params: { path } }),

  // 插件管理（插件 = 知识包 + 可选工具）
  listPlugins: () => api.get('/plugins'),
  getPluginFiles: (id) => api.get('/plugins/' + id + '/files'),
  togglePlugin: (id, enabled) => api.post('/plugins/' + id + '/toggle', null, { params: { enabled } }),
  deletePlugin: (id) => api.delete('/plugins/' + id),
  importPlugin: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/plugins/import', fd, { timeout: 60000 })
  },
  exportPlugin: (id) => api.get('/plugins/' + id + '/export', { responseType: 'blob', timeout: 60000 }),
  inspectPluginTools: (id) => api.post('/plugins/' + id + '/inspect', null, { timeout: 30000 }),
  testPluginTool: (id, toolName, args) => api.post('/plugins/' + id + '/test', { tool_name: toolName, args }, { timeout: 120000 }),

  // 全局设置
  getSettings: () => api.get('/settings'),
  setSetting: (key, value) => api.post('/settings', { key, value }),

  // 智能客服（流式接口 /chat/stream 由 Home.vue 用 fetch 直连，axios 不支持流式）

  // 会话管理
  listChats: () => api.get('/chats'),
  getChat: (id) => api.get('/chats/' + id),
  createChat: (data) => api.post('/chats', data),
  updateChat: (id, data) => api.patch('/chats/' + id, data),
  deleteChat: (id) => api.delete('/chats/' + id)
}
