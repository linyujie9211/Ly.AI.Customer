# Ly.AI.Customer

智能客服机器人：基于大模型的对话式客服系统，支持知识库 RAG 检索增强、插件化扩展（function calling）、多模型管理与流式对话。

## 功能特性

- **智能对话**：流式输出（SSE）、多会话管理、历史记录持久化
- **RAG 知识库**：支持本地文件 / Elasticsearch 双存储模式；文档解析（txt/md/pdf/docx/xlsx/csv）、分块、向量化，BM25 关键词 + faiss 向量**混合检索**
- **插件系统**：内置插件出厂模板 + 用户自定义插件（`plugin.json` 元数据 + `skill.md` 知识包 + `tools.py` 工具），工具经 function calling 由 LLM 自主编排调用；插件默认禁用、审查后手动启用
- **模型管理**：对接任意 OpenAI 兼容 API；按类型（对话 / Embedding 等）管理模型，支持复制、启用开关、按类型设置默认模型
- **用户认证**：登录 / 注册，账号数据存 SQLite

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python、FastAPI、uvicorn、SQLite |
| 前端 | Vue 3、Vite、vue-router、axios |
| 检索 | jieba、rank-bm25、faiss-cpu、numpy |
| 文档解析 | pypdf、pdfplumber、python-docx、openpyxl |

## 项目结构

```
Ly.AI.Customer/
├── main.py                  # 后端入口（FastAPI，127.0.0.1:8000）
├── requirements.txt
├── app/                     # 后端源码
│   ├── server.py            # 全部 REST API 路由
│   ├── agent.py             # 对话编排：RAG 注入 + 插件知识包路由 + 工具调用循环
│   ├── knowledge.py         # 知识库：解析 / 分块 / 向量化 / 混合检索
│   ├── storage.py           # SQLite 存储层（账号 / 模型 / 设置 / 会话）
│   ├── plugin_manager.py    # 插件扫描、动态加载 / 卸载、内置插件落盘
│   ├── tools/registry.py    # @tool 装饰器与工具注册表
│   ├── logger.py            # 日志（滚动文件 + 控制台）
│   ├── paths.py             # 路径定义（运行时工作区等）
│   └── plugins_seed/        # 内置插件出厂模板（首次启动落盘到 workspace/plugins）
├── web/                     # 前端源码（Vue 3 + Vite）
│   └── src/
│       ├── views/           # Home（聊天）/ Login / Register / Models（模型管理）
│       ├── components/      # SettingsModal / KnowledgeBase / PluginsManage
│       └── composables/     # useMaskClose 等复用逻辑
└── workspace/               # 运行时生成目录（git 忽略，勿删）
    ├── data/                # SQLite 数据库
    ├── logs/                # 运行日志
    ├── knowledge_base/      # 本地知识库（分块 + 向量索引）
    └── plugins/             # 插件运行时目录（内置 + 用户插件）
```

## 快速开始

### 1. 启动后端

```bash
pip install -r requirements.txt
python main.py
```

服务运行在 `http://127.0.0.1:8000`。首次启动会自动创建 `workspace/` 目录并落盘内置插件。

### 2. 启动前端

```bash
cd web
npm install
npm run dev
```

访问 `http://localhost:5173`。

### 3. 登录

默认管理员账号：

```
用户名：admin
密码：agent_admin
```

### 4. 配置模型

进入 **系统设置 → 模型配置 → 添加模型**，填入 OpenAI 兼容 API 的地址与 Key：

- 至少添加一个 **对话** 类型模型并启用（建议设为默认）
- 如需使用知识库向量化检索，还需添加一个 **Embedding** 类型模型

## 使用说明

- **对话**：首页聊天窗口直接提问；回答会自动注入知识库检索结果，命中插件知识包时按路由注入领域知识，需要工具时由 LLM 发起 function calling
- **知识库**：系统设置 → 知识库，新建知识库后上传文档并点击"构建索引"；支持切换本地 / ES 存储模式
- **插件**：系统设置 → 插件管理，可查看内置插件、导入或在线新建插件；`tools.py` 仅在插件启用后才会被加载执行
- **模型**：系统设置 → 模型配置，支持编辑、复制、删除；同类型模型仅有一个默认，在非默认模型上点击"设默认"即可切换

## 运行时目录（workspace/）

所有运行时生成的文件统一收敛在 `workspace/` 下，便于备份与清理：

| 子目录 | 内容 |
|---|---|
| `data/` | SQLite 数据库（账号、模型、设置、会话） |
| `logs/` | 滚动日志（单文件 5MB，保留 3 个） |
| `knowledge_base/` | 知识库分块数据与 faiss 向量索引 |
| `plugins/` | 插件运行时目录（内置插件首次启动时从 `plugins_seed` 落盘） |

## 安全约定

- 新导入 / 新建的插件默认 `enabled=false`，需在插件管理页审查代码后手动启用
- 插件 `tools.py` 仅在插件启用时被动态加载执行
- 密码加盐哈希存储，不落明文
