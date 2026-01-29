# PetForge 批量处理工坊

> **版本**: 2.1  
> **页面地址**: http://localhost:5173/batch

---

## 快速了解

**PetForge 批量处理工坊** 是一个基于飞书多维表格的批量视频生产平台，专为宠物类短视频内容的规模化生产而设计。

### 核心特性

- **批量处理**: 一键生成多个视频的分镜脚本和视频段
- **飞书集成**: 以飞书多维表格为协作中心，支持团队分工
- **AI 驱动**: 使用 DeepSeek 生成分镜，VEO 生成视频
- **四端同步**: 数据库、本地文件、飞书、前端数据一致

---

## 工作流程

```
连接飞书 → 生成分镜 → 编辑优化 → 生成视频 → 同步云盘
```

| 步骤 | 操作 | 产出 |
|-----|------|------|
| 1. 连接飞书 | 配置表格凭证 | 加载任务列表 |
| 2. 生成分镜 | 选择任务，一键生成 | 7 段分镜脚本 |
| 3. 编辑优化 | 预览并修改提示词 | 优化后的分镜 |
| 4. 生成视频 | 逐段推进生成 | 7 个视频片段 |
| 5. 同步云盘 | 上传到飞书云盘 | 团队可访问的视频 |

---

## 快速开始

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt
cd video-studio && npm install

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API 密钥
```

### 2. 启动服务

```bash
# 后端
python -m paretoai.server

# 前端
cd video-studio && npm run dev
```

### 3. 配置飞书

1. 创建飞书应用并获取 App ID 和 App Secret
2. 创建多维表格，包含以下字段：
   - `opening_image_url`: 首帧图片（附件或 URL）
   - `release_date`: 发布日期
   - `template_id`: 模板 ID（可选）
3. 在页面中填写凭证并连接

---

## 文档索引

| 文档 | 描述 | 适合人群 |
|-----|------|---------|
| [产品规格](./PETFORGE_PRODUCT_SPEC.md) | 用户动线、功能模块、数据架构 | 产品/运营 |
| [技术指南](./PETFORGE_TECHNICAL_GUIDE.md) | 系统架构、代码实现、核心流程 | 开发者 |
| [文件清单](./PETFORGE_FILES.md) | 所有相关文件的结构化列表 | 开发者 |

---

## 技术栈

| 层次 | 技术 |
|-----|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind CSS |
| 后端 | Python 3.12 + FastAPI + SQLModel |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| LLM | DeepSeek API |
| 视频生成 | Google VEO API |

---

## 项目结构

```
├── video-studio/           # 前端代码
│   └── src/
│       ├── pages/          # 页面组件
│       ├── components/     # UI 组件
│       └── services/       # API 服务
├── paretoai/               # 后端代码
│   ├── routes/             # API 路由
│   ├── services/           # 业务服务
│   └── prompts/            # LLM 提示词
├── data/                   # 数据存储
│   └── uploads/projects/   # 项目文件
└── docs/                   # 文档
```

---

## 常用操作

### 检查数据一致性

```bash
python scripts/verify_all_data_consistency.py
```

### 查看数据库状态

```bash
python scripts/inspect_db.py
```

### 运行测试

```bash
pytest tests/integration/test_batch_workshop_v2.py -v
```

---

## 已知问题

V2.1 版本已修复的问题：

| 问题 | 状态 |
|-----|------|
| 段生成完成后状态显示不正确 | ✅ 已修复 |
| 编辑框无法输入 | ✅ 已修复 |
| 生成失败后状态未回退 | ✅ 已修复 |

---

## 联系方式

如有问题，请联系项目负责人或查阅详细文档。

---

*文档更新时间: 2026-01-27*
