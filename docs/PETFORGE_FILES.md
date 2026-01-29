# PetForge 批量处理工坊 - 文件清单

> 页面地址: http://localhost:5173/batch
> 功能: 批量视频生成工坊，集成飞书多维表格

---

## 📁 文件结构总览

```
PetForge 相关文件（共 ~35 个核心文件）

├── 前端 (video-studio/)
│   ├── src/pages/
│   │   ├── BatchPage.tsx              ⭐ 主页面
│   │   ├── BatchPage.reducer.ts       状态管理
│   │   └── BatchPage.types.ts         类型定义
│   ├── src/components/batch/
│   │   ├── TaskTable.tsx              任务列表
│   │   ├── TaskDetail.tsx             任务详情
│   │   ├── StatsBar.tsx               统计栏
│   │   ├── FeishuConfig.tsx           飞书配置
│   │   ├── PromptEditModal.tsx        分镜编辑弹窗
│   │   ├── BatchPromptEditModal.tsx   批量编辑弹窗
│   │   ├── ApiJobQueueDrawer.tsx      API队列抽屉
│   │   └── index.ts                   导出
│   ├── src/services/
│   │   └── batchApiService.ts         API 服务
│   └── src/lib/
│       └── batchUtils.ts              工具函数
│
├── 后端 (paretoai/)
│   ├── routes/
│   │   ├── batch.py                   ⭐ 批量处理 API
│   │   ├── proxy.py                   代理服务
│   │   ├── video.py                   视频 API
│   │   └── storage.py                 存储 API
│   ├── services/
│   │   ├── feishu_bitable.py          ⭐ 飞书表格服务
│   │   ├── feishu_drive_service.py    飞书云盘服务
│   │   ├── feishu_user_oauth_store.py OAuth 存储
│   │   ├── storyboard_service.py      ⭐ 分镜生成
│   │   ├── video_segment_service.py   ⭐ 视频段生成
│   │   ├── task_status_service.py     ⭐ 任务状态
│   │   ├── project_path_service.py    路径服务
│   │   ├── project_lock_service.py    并发锁
│   │   ├── veo_client.py              VEO API
│   │   ├── api_job_store.py           任务队列
│   │   └── sync_state_store.py        同步状态
│   ├── prompts/
│   │   └── storyboard_generation.txt  ⭐ 分镜提示词
│   ├── models.py                      数据模型
│   ├── db.py                          数据库
│   ├── config.py                      配置
│   └── server.py                      服务入口
│
└── 数据 (data/)
    ├── feishu_connections.json        飞书配置
    └── sync_state.json                同步状态
```

---

## 一、前端文件详情

### 1.1 页面 (`video-studio/src/pages/`)

| 文件 | 行数 | 描述 |
|-----|------|------|
| `BatchPage.tsx` | ~800 | **主页面**：任务列表、飞书连接、操作按钮 |
| `BatchPage.reducer.ts` | ~150 | 状态管理 reducer |
| `BatchPage.types.ts` | ~100 | TypeScript 类型定义 |

### 1.2 组件 (`video-studio/src/components/batch/`)

| 文件 | 行数 | 描述 |
|-----|------|------|
| `TaskTable.tsx` | ~400 | 任务列表表格，显示所有任务状态 |
| `TaskDetail.tsx` | ~500 | 右侧详情面板，显示分镜预览和视频 |
| `StatsBar.tsx` | ~100 | 顶部统计栏（总数/完成/进行中） |
| `FeishuConfig.tsx` | ~300 | 飞书配置面板（连接/断开） |
| `PromptEditModal.tsx` | ~200 | 单个分镜编辑弹窗 |
| `BatchPromptEditModal.tsx` | ~250 | 批量推进时的编辑弹窗 |
| `ApiJobQueueDrawer.tsx` | ~200 | API 任务队列抽屉 |
| `index.ts` | ~10 | 组件导出 |

### 1.3 服务和工具

| 文件 | 描述 |
|-----|------|
| `src/services/batchApiService.ts` | 批量处理 API 调用封装 |
| `src/lib/batchUtils.ts` | 工具函数（状态转换等） |
| `src/types/index.ts` | 全局类型定义 |

---

## 二、后端文件详情

### 2.1 API 路由 (`paretoai/routes/`)

| 文件 | 行数 | 核心 API |
|-----|------|---------|
| `batch.py` | ~3500 | `/api/batch/*` - 批量处理所有 API |
| `proxy.py` | ~100 | `/api/proxy/*` - LLM 和图片代理 |
| `video.py` | ~600 | `/api/video/*` - 视频生成 |
| `storage.py` | ~200 | `/api/storage/*` - 文件存储 |

### batch.py 核心 API

| API | 方法 | 描述 |
|-----|------|------|
| `/api/batch/tasks` | GET | 获取任务列表 |
| `/api/batch/connect-feishu` | POST | 连接飞书表格 |
| `/api/batch/disconnect-feishu` | POST | 断开飞书连接 |
| `/api/batch/generate-storyboards` | POST | 批量生成分镜 |
| `/api/batch/generate-segments` | POST | 批量生成视频段 |
| `/api/batch/sync-to-feishu` | POST | 同步到飞书 |
| `/api/batch/cascade-redo` | POST | 级联重做 |
| `/api/batch/edit-prompt` | POST | 编辑分镜提示词 |

### 2.2 业务服务 (`paretoai/services/`)

| 文件 | 行数 | 描述 |
|-----|------|------|
| `feishu_bitable.py` | ~1200 | **飞书多维表格服务**：记录CRUD、附件上传 |
| `feishu_drive_service.py` | ~1000 | 飞书云盘服务：文件上传到云盘 |
| `feishu_user_oauth_store.py` | ~200 | 用户 OAuth Token 存储 |
| `storyboard_service.py` | ~800 | **分镜生成服务**：调用 LLM 生成分镜 |
| `video_segment_service.py` | ~1200 | **视频段生成服务**：调用 VEO 生成视频 |
| `task_status_service.py` | ~400 | **任务状态服务**：数据库状态管理 |
| `project_path_service.py` | ~350 | 项目路径服务：V2 目录结构 |
| `project_lock_service.py` | ~250 | 项目锁服务：防止并发冲突 |
| `veo_client.py` | ~350 | VEO API 客户端 |
| `api_job_store.py` | ~100 | API 任务队列存储 |
| `sync_state_store.py` | ~300 | 同步状态存储 |

### 2.3 提示词模板 (`paretoai/prompts/`)

| 文件 | 描述 |
|-----|------|
| `storyboard_generation.txt` | **当前使用**的分镜生成提示词 |
| `storyboard_generation_v1~v4.txt` | 历史版本（可选保留） |

### 2.4 核心模块

| 文件 | 描述 |
|-----|------|
| `models.py` | SQLModel 数据模型（BatchTask 等） |
| `db.py` | 数据库连接和会话管理 |
| `config.py` | 配置管理 |
| `server.py` | FastAPI 应用入口（注册 batch 路由） |

---

## 三、数据文件

### 3.1 配置文件

| 文件 | 描述 | 敏感性 |
|-----|------|--------|
| `data/feishu_connections.json` | 飞书连接配置 | ⚠️ 包含 app_secret |
| `data/sync_state.json` | 同步状态 | 安全 |
| `data/feishu_user_oauth_tokens.json` | 用户 Token | ⚠️ 敏感 |

### 3.2 数据库

| 文件 | 描述 |
|-----|------|
| `paretoai.db` | SQLite 数据库（batch_tasks 表） |

### 3.3 项目数据目录结构

```
data/uploads/projects/
├── {YYYY-MM-DD}/              # 发布日期
│   └── eating-template/       # 模板 ID
│       └── {project_id}/      # 项目 ID
│           ├── opening_image.jpg
│           ├── storyboard.json
│           ├── meta.json
│           ├── frames/
│           │   ├── segment_0_first.jpg
│           │   └── segment_0_last.jpg
│           └── segments/
│               └── segment_0_segment.mp4
```

---

## 四、完整文件清单

### ✅ 必须包含（35 个核心文件）

```
# 前端页面
video-studio/src/pages/BatchPage.tsx
video-studio/src/pages/BatchPage.reducer.ts
video-studio/src/pages/BatchPage.types.ts

# 前端组件
video-studio/src/components/batch/TaskTable.tsx
video-studio/src/components/batch/TaskDetail.tsx
video-studio/src/components/batch/StatsBar.tsx
video-studio/src/components/batch/FeishuConfig.tsx
video-studio/src/components/batch/PromptEditModal.tsx
video-studio/src/components/batch/BatchPromptEditModal.tsx
video-studio/src/components/batch/ApiJobQueueDrawer.tsx
video-studio/src/components/batch/index.ts

# 前端服务
video-studio/src/services/batchApiService.ts
video-studio/src/lib/batchUtils.ts
video-studio/src/types/index.ts

# 后端路由
paretoai/routes/batch.py
paretoai/routes/proxy.py
paretoai/routes/video.py
paretoai/routes/storage.py

# 后端服务
paretoai/services/feishu_bitable.py
paretoai/services/feishu_drive_service.py
paretoai/services/feishu_user_oauth_store.py
paretoai/services/storyboard_service.py
paretoai/services/video_segment_service.py
paretoai/services/task_status_service.py
paretoai/services/project_path_service.py
paretoai/services/project_lock_service.py
paretoai/services/veo_client.py
paretoai/services/api_job_store.py
paretoai/services/sync_state_store.py

# 提示词
paretoai/prompts/storyboard_generation.txt

# 核心模块
paretoai/models.py
paretoai/db.py
paretoai/config.py
paretoai/server.py
paretoai/__init__.py
paretoai/services/__init__.py
paretoai/routes/__init__.py
```

### ⚠️ 依赖文件（前端需要）

```
# UI 组件（BatchPage 依赖）
video-studio/src/components/ui/button.tsx
video-studio/src/components/ui/card.tsx
video-studio/src/components/ui/textarea.tsx
video-studio/src/components/ui/toast.tsx
video-studio/src/lib/utils.ts

# 前端入口
video-studio/src/App.tsx
video-studio/src/main.tsx
video-studio/src/index.css

# 前端配置
video-studio/package.json
video-studio/vite.config.ts
video-studio/tailwind.config.js
video-studio/tsconfig.json
video-studio/index.html
```

### ⚠️ 配置文件（需要示例）

```
.env                           → .env.example
data/feishu_connections.json   → data/feishu_connections.json.example
```

---

## 五、打包命令

```bash
# 创建 PetForge 分支
git checkout -b feature/petforge-batch-workshop

# 只提交相关文件
git add video-studio/src/pages/Batch*
git add video-studio/src/components/batch/
git add video-studio/src/services/batchApiService.ts
git add video-studio/src/lib/batchUtils.ts

git add paretoai/routes/batch.py
git add paretoai/routes/proxy.py
git add paretoai/routes/video.py
git add paretoai/routes/storage.py

git add paretoai/services/feishu*.py
git add paretoai/services/storyboard_service.py
git add paretoai/services/video_segment_service.py
git add paretoai/services/task_status_service.py
git add paretoai/services/project_*.py
git add paretoai/services/veo_client.py
git add paretoai/services/api_job_store.py
git add paretoai/services/sync_state_store.py
git add paretoai/services/__init__.py

git add paretoai/prompts/storyboard_generation.txt
git add paretoai/models.py
git add paretoai/db.py
git add paretoai/config.py
git add paretoai/server.py

git commit -m "feat: PetForge 批量处理工坊"
```

---

## 六、文档文件

### 6.1 架构文档 (`docs/architecture/`)

| 文件 | 描述 |
|-----|------|
| `BATCH_STATUS_PROGRESS_FLOW.md` | 批量处理状态流程图 |
| `DATA_FLOW_FIXES_SUMMARY.md` | 数据流修复总结 |
| `PROMPT_EDIT_DATA_FLOW.md` | 提示词编辑数据流 |
| `refactoring/DATA_STRUCTURE_V2.md` | V2 数据结构设计 |

### 6.2 代码变更日志 (`docs/changelogs/`)

| 文件 | 描述 |
|-----|------|
| `CODE_CHANGES_C1b_generate_segments_lock.md` | 段生成并发锁 |
| `CODE_CHANGES_C2_feishu_retry.md` | 飞书 API 重试机制 |
| `CODE_CHANGES_C3_overwrite_protection.md` | 覆盖保护机制 |

### 6.3 问题调查 (`docs/investigations/`)

| 文件 | 描述 |
|-----|------|
| `ISSUE-20260126_Manual_Test_Fixes.md` | **主要问题修复记录** |
| `ISSUE-20260127_Feishu_Association_Root_Cause.md` | 飞书关联问题根因 |
| `BATCH_CODE_REVIEW.md` | 批量处理代码审查 |
| `DRIVE_FOLDER_TOKEN_ISSUE.md` | 云盘 Token 问题 |
| `多选功能问题总结.md` | 多选功能问题 |
| `问题总结.md` | 问题汇总 |

### 6.4 工作流文档 (`docs/workflows/`)

| 文件 | 描述 |
|-----|------|
| `FEISHU_FIELDS_LOGIC.md` | 飞书字段逻辑 |
| `PROMPT_FIELD_LOGIC.md` | 提示词字段逻辑 |
| `SYNC_FIELDS.md` | 同步字段说明 |

### 6.5 其他文档

| 文件 | 描述 |
|-----|------|
| `docs/features/Batch_Workshop_Product_Brief.md` | 产品简介 |
| `docs/migration/MIGRATION_GUIDE.md` | 迁移指南 |
| `docs/reviews/2026-01-25_BatchWorkshop_V2_Review.md` | V2 评审 |
| `docs/reviews/2026-01-25_V2_Refactoring_Completed.md` | V2 重构完成 |
| `docs/specs/STORAGE_STRUCTURE.md` | 存储结构规范 |
| `docs/checklists/TEST_EDIT_SEGMENT1_CHECKLIST.md` | 测试检查清单 |

---

## 七、测试文件

### 7.1 测试代码 (`tests/`)

| 文件 | 描述 |
|-----|------|
| `tests/integration/test_batch_workshop_v2.py` | **V2 集成测试** |
| `tests/plans/test_plan_batch_workshop_v2.md` | 测试计划 |

### 7.2 测试报告 (`tests/integration/`)

| 文件 | 描述 |
|-----|------|
| `TEST_REPORT_batch_workshop_v2.md` | 第一轮测试报告 |
| `TEST_REPORT_batch_workshop_v2_round2.md` | 第二轮测试报告 |
| `TEST_REPORT_batch_workshop_v2_round3.md` | 第三轮测试报告 |
| `TEST_REPORT_batch_workshop_v2_FINAL.md` | 最终测试报告 |
| `TEST_SUMMARY_batch_workshop_v2.md` | 测试总结 |

---

## 八、工具脚本

### 8.1 数据检查脚本 (`scripts/`)

| 文件 | 描述 |
|-----|------|
| `verify_all_data_consistency.py` | **四端数据一致性检查** |
| `compare_feishu_and_db.py` | 飞书与数据库比对 |
| `compare_storyboard.py` | 分镜数据比对 |
| `check_feishu_fields.py` | 检查飞书字段 |
| `check_feishu_running_tasks.py` | 检查运行中的任务 |

### 8.2 数据迁移脚本

| 文件 | 描述 |
|-----|------|
| `migrate_local_to_db.py` | 本地数据迁移到数据库 |
| `migrate_project_structure.py` | 项目结构迁移 |
| `initialize_database.py` | 数据库初始化 |

### 8.3 同步脚本

| 文件 | 描述 |
|-----|------|
| `sync_storyboard_to_feishu.py` | 同步分镜到飞书 |
| `inspect_db.py` | 数据库检查 |

---

## 九、本地存储结构

### 9.1 项目数据目录

```
data/uploads/projects/
├── 2026-01-24/                    # 发布日期分组
│   └── eating-template/           # 模板分组
│       ├── 13748642fd3a/          # 项目目录
│       │   ├── opening_image.jpg  # 首帧图片
│       │   ├── storyboard.json    # 分镜数据
│       │   ├── meta.json          # 元数据（状态等）
│       │   ├── frames/            # 视频帧目录
│       │   │   ├── segment_0_first.jpg
│       │   │   └── segment_0_last.jpg
│       │   └── segments/          # 视频段目录
│       │       └── segment_0_segment.mp4
│       ├── 2ca205ec6438/
│       ├── 591c041b74bb/
│       └── cbd1a32addfc/
├── 2026-01-25/
│   └── eating-template/
│       ├── 4f91e593108d/
│       ├── 75157fe0deed/
│       ├── 7de03e4a4aeb/
│       ├── 98eadf86c7db/
│       └── c8fdcd8ae95e/
└── 2026-01-27/
    └── eating-template/
        ├── 834ea4c71a47/
        ├── 7f0dbf09be55/
        ├── b4af58217cad/
        ├── f063059bedba/
        └── fa31491e1ad4/
```

### 9.2 单个项目文件说明

| 文件 | 格式 | 描述 |
|-----|------|------|
| `opening_image.jpg` | JPEG | 首帧图片（从飞书下载） |
| `storyboard.json` | JSON | 分镜数据（LLM 生成） |
| `meta.json` | JSON | 项目元数据（状态、进度、错误） |
| `frames/segment_N_first.jpg` | JPEG | 第 N 段首帧 |
| `frames/segment_N_last.jpg` | JPEG | 第 N 段尾帧 |
| `segments/segment_N_segment.mp4` | MP4 | 第 N 段视频 |

### 9.3 meta.json 结构

```json
{
  "status": "storyboard_ready",
  "progress": "5/7段已完成",
  "error_message": "",
  "updated_at": "2026-01-27T12:00:00"
}
```

### 9.4 storyboard.json 结构

```json
[
  {
    "segment_index": 0,
    "description": "宠物开始吃东西...",
    "motion_prompt": "缓慢低头，开始进食",
    "duration": 5
  },
  {
    "segment_index": 1,
    "description": "...",
    ...
  }
]
```

---

## 十、核心文档

### 10.1 产品与技术文档

| 文件 | 描述 |
|-----|------|
| `docs/PETFORGE_README.md` | **项目入口文档**（快速上手） |
| `docs/PETFORGE_PRODUCT_SPEC.md` | **产品规格说明书**（用户动线/功能模块/数据架构） |
| `docs/PETFORGE_TECHNICAL_GUIDE.md` | **技术实现指南**（架构/代码/流程） |
| `docs/PETFORGE_DIAGNOSTIC_REPORT.md` | **技术诊断报告**（深度代码审查/问题清单/优化建议） |
| `docs/PETFORGE_FILES.md` | 文件清单（本文档） |

### 10.2 问题调查文档

| 文件 | 描述 |
|-----|------|
| `docs/investigations/ISSUE-20260126_Manual_Test_Fixes.md` | 手工测试问题修复日志（问题#1-#14） |
| `docs/investigations/ISSUE-20260127_Feishu_Association_Root_Cause.md` | 飞书关联问题根因分析 |
| `docs/investigations/ISSUE-20260127_Problem14_RootCause.md` | 问题#14深度根因分析 |

### 10.3 文档结构

```
docs/
├── PETFORGE_README.md              ⭐ 入口文档
├── PETFORGE_PRODUCT_SPEC.md        ⭐ 产品规格
├── PETFORGE_TECHNICAL_GUIDE.md     ⭐ 技术实现
├── PETFORGE_DIAGNOSTIC_REPORT.md   ⭐ 诊断报告
├── PETFORGE_FILES.md               ⭐ 文件清单
├── architecture/                    架构文档
├── changelogs/                      变更日志
├── investigations/                  问题调查
│   ├── ISSUE-20260126_Manual_Test_Fixes.md
│   ├── ISSUE-20260127_Feishu_Association_Root_Cause.md
│   └── ISSUE-20260127_Problem14_RootCause.md
└── workflows/                       工作流文档
```

---

## 十一、完整文件统计

| 分类 | 文件数 |
|-----|--------|
| 前端页面 | 3 |
| 前端组件 | 8 |
| 前端服务 | 2 |
| 后端路由 | 4 |
| 后端服务 | 11 |
| 提示词 | 1 |
| 核心模块 | 4 |
| 核心文档 | 5 |
| 问题调查文档 | 3 |
| 架构文档 | 4 |
| 代码变更日志 | 3 |
| 工作流文档 | 3 |
| 其他文档 | 6 |
| 测试代码 | 2 |
| 测试报告 | 5 |
| 工具脚本 | 10 |
| **总计** | **~80 个文件** |

---

*文档更新时间: 2026-01-27 (项目收尾版本)*
