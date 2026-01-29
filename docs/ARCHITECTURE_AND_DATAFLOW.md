# PetForge2 技术架构与数据流文档

> 最后更新: 2026-01-29

## 目录

1. [系统概述](#一系统概述)
2. [技术架构](#二技术架构)
3. [数据流详解](#三数据流详解)
4. [核心模块说明](#四核心模块说明)
5. [数据一致性保障](#五数据一致性保障)
6. [**V2 架构重构**](#六v2-架构重构2026-01-29)
7. [附录：字段说明](#七附录字段说明)

---

## 一、系统概述

PetForge2 是一个宠物视频自动化生成平台，通过与飞书多维表格集成，实现从宠物图片到完整视频的端到端自动化流程。

### 核心能力

- **分镜脚本生成**：基于宠物图片和模板，通过 LLM 自动生成 7 段视频脚本
- **视频批量生成**：调用视频生成 API（Kling/Veo），支持并发批量处理
- **飞书集成**：与飞书多维表格双向同步，支持协作管理
- **断点续传**：支持从任意分段重新生成，历史版本自动备份

### 核心原则

**数据库是唯一事实来源（Single Source of Truth）**

所有数据变更遵循以下优先级：
1. **数据库** ← 与外部 API 交互后首先更新
2. **本地文件** ← 从数据库同步（作为缓存/备份）
3. **飞书表格** ← 从数据库同步（用于协作展示）

---

## 二、技术架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                           前端 (React + Vite)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │ BatchPage   │  │ TaskDetail  │  │ FeishuConfig│  │ PromptEdit  │ │
│  │ (任务列表)  │  │ (任务详情)  │  │ (飞书配置)  │  │ (提示词编辑)│ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
│                              │                                       │
│                    batchApiService.ts                               │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │ HTTP API
┌─────────────────────────────────┼───────────────────────────────────┐
│                           后端 (FastAPI)                             │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                      routes/batch.py                            ││
│  │  • /connect-table      • /generate-storyboards                  ││
│  │  • /generate-segments  • /edit-and-regenerate                   ││
│  │  • /cascade-redo       • /sync-videos                           ││
│  └─────────────────────────────────────────────────────────────────┘│
│                              │                                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐           │
│  │FeishuBitable  │  │VideoSegment   │  │TaskStatus     │           │
│  │Service        │  │Service        │  │Service        │           │
│  │(飞书API)      │  │(视频生成)     │  │(状态管理)     │           │
│  └───────────────┘  └───────────────┘  └───────────────┘           │
│                              │                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    SQLite (paretoai.db)                       │  │
│  │  batch_tasks: project_id, storyboard_json, segment_urls, ...  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │   飞书多维表格   │  │   外部 LLM API   │  │  视频生成 API   │
    │  (数据协作)     │  │  (分镜生成)      │  │  (Kling/Veo)   │
    └─────────────────┘  └─────────────────┘  └─────────────────┘
```

### 2.2 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18 + TypeScript | 单页应用 |
| **构建工具** | Vite | 快速开发服务器 |
| **UI 框架** | Tailwind CSS | 原子化 CSS |
| **后端** | FastAPI + Python 3.11 | 异步 Web 框架 |
| **数据库** | SQLite + SQLModel | 轻量级关系数据库 |
| **外部服务** | 飞书开放平台、Kling API、OpenAI API | 第三方集成 |

### 2.3 目录结构

```
PetForge2/
├── paretoai/                    # 后端代码
│   ├── server.py               # FastAPI 入口
│   ├── routes/
│   │   └── batch.py            # 批量处理路由（核心）
│   ├── services/
│   │   ├── feishu_bitable.py   # 飞书多维表格服务
│   │   ├── video_segment_service.py  # 视频生成服务
│   │   ├── task_status_service.py    # 任务状态服务
│   │   ├── project_path_service.py   # 项目路径服务
│   │   └── project_lock_service.py   # 并发锁服务
│   ├── models.py               # 数据模型
│   └── prompts/                # LLM 提示词模板
│
├── video-studio/               # 前端代码
│   ├── src/
│   │   ├── pages/
│   │   │   └── BatchPage.tsx   # 批量处理页面
│   │   ├── components/batch/   # 批量处理组件
│   │   └── services/
│   │       └── batchApiService.ts  # API 服务
│   └── vite.config.ts
│
├── data/
│   └── uploads/projects/       # 项目文件存储
│       └── {date}/{template}/{project_id}/
│           ├── opening_image.jpg
│           ├── storyboard.json
│           ├── meta.json
│           ├── segments/       # 视频文件
│           └── frames/         # 帧图片
│
├── paretoai.db                 # SQLite 数据库
└── docs/                       # 文档目录
```

---

## 三、数据流详解

### 3.1 阶段一：分镜生成（Storyboard Generation）

#### 流程图

```
┌─────────┐    ①获取数据   ┌─────────┐    ②调用LLM    ┌─────────┐
│  飞书   │ ─────────────> │  后端   │ ─────────────> │外部 LLM │
│多维表格 │  opening_image │         │  image+prompt  │  API    │
│         │  template_id   │         │                │         │
└─────────┘                └─────────┘                └─────────┘
                                │                          │
                                │    ③返回分镜脚本         │
                                ▼                          │
                           ┌─────────┐ <───────────────────┘
                           │ 数据库  │  storyboard_json
                           │         │  (7段脚本)
                           └─────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │ ④同步          │ ⑤同步           │ ⑥同步
              ▼                 ▼                 ▼
        ┌─────────┐       ┌─────────┐       ┌─────────┐
        │本地文件 │       │  飞书   │       │ 前端UI  │
        │storyboard│      │storyboard│      │(刷新)   │
        │.json    │       │_json字段│       │         │
        └─────────┘       └─────────┘       └─────────┘
```

#### 详细步骤

1. **从飞书获取源数据**
   - `opening_image_url`：宠物照片（飞书附件）
   - `template_id`：视频模板类型（如 `eating-template`）
   - `release_date`：发布日期

2. **生成 Project ID**
   - 格式：12位十六进制随机字符串（如 `3242d9ae0752`）
   - 用途：唯一标识项目，关联所有后续数据

3. **调用外部 LLM**
   - 输入：opening_image + template prompt
   - 输出：包含 7 个分段的 storyboard.json

4. **数据写入顺序**
   ```
   ① 数据库.storyboard_json ← LLM 返回结果（主数据源）
   ② 本地 storyboard.json   ← 同步写入
   ③ 飞书.storyboard_json   ← 同步写入
   ```

#### API 端点

```
POST /api/batch/generate-storyboards
{
  "table_id": "tblXXX",
  "record_ids": ["recXXX", "recYYY"],
  "concurrency": 10,
  "overwrite": false
}
```

---

### 3.2 阶段二：视频生成（Video Generation）

#### 流程图

```
┌─────────┐    ①发起请求    ┌─────────┐    ②调用API    ┌─────────┐
│  前端   │ ─────────────> │  后端   │ ─────────────> │视频API  │
│(批量/   │  segment_index │         │  prompt +      │(Kling)  │
│ 单个)   │  + record_ids  │         │  first_frame   │         │
└─────────┘                └─────────┘                └─────────┘
                                │                          │
                                │    ③返回视频URL          │
                                ▼                          │
                           ┌─────────┐ <───────────────────┘
                           │ 数据库  │  video_url (在线链接)
                           └─────────┘
                                │
              ┌─────────────────┼─────────────────┐
              │ ④更新          │ ⑤下载           │ ⑥同步
              ▼                 ▼                 ▼
        ┌─────────┐       ┌─────────┐       ┌─────────┐
        │storyboard│      │本地文件 │       │  飞书   │
        │_json +  │       │segments/│       │segment_ │
        │segment_ │       │frames/  │       │X_video_ │
        │urls     │       │         │       │url      │
        └─────────┘       └─────────┘       └─────────┘
```

#### 详细步骤

1. **前端发起请求**
   - 支持批量选择多条记录
   - 指定要生成的 segment_index（0-6）

2. **后端调用视频 API**
   - 读取 prompt（从 storyboard.json）
   - 获取 first_frame：
     - 段0：使用 opening_image
     - 其他段：使用前一段的 last_frame
   - 轮询等待生成完成（约 2-3 分钟）

3. **数据更新顺序**
   ```
   ① 本地 storyboard.json.video_url  ← 在线URL（即时更新，前端立即可用）
   ② 数据库.storyboard_json          ← 更新 video_url + status
   ③ 数据库.segment_urls             ← 完整结果（video_url, status, frames）
   ④ 本地 segments/                  ← 下载视频文件
   ⑤ 本地 frames/                    ← 提取首尾帧（用于下一段生成）
   ⑥ 飞书.storyboard_json            ← 同步更新
   ⑦ 飞书.segment_X_video_url        ← 同步更新
   ```

#### API 端点

```
POST /api/batch/generate-segments
{
  "table_id": "tblXXX",
  "record_ids": ["recXXX", "recYYY"],
  "segment_index": 0,
  "concurrency": 5
}
```

---

### 3.3 编辑并重新生成（Edit & Regenerate）

#### 触发场景

用户在前端编辑某个分段的提示词字段（crucial、action、sound、negative_constraint），然后点击"确认并重新生成"。

#### 流程图

```
┌─────────┐    ①编辑字段    ┌─────────┐    ②重建prompt   ┌─────────┐
│  前端   │ ─────────────> │  后端   │ ─────────────────>│ 数据库  │
│(编辑框) │  crucial,      │         │                   │         │
│         │  action, ...   │         │                   │         │
└─────────┘                └─────────┘                   └─────────┘
                                │                             │
                                │    ③调用视频API             │
                                ▼                             │
                           ┌─────────┐                        │
                           │视频API  │                        │
                           └─────────┘                        │
                                │                             │
                                │    ④返回新视频              │
                                ▼                             │
                           ┌─────────┐ <──────────────────────┘
                           │ 回写结果│  更新 storyboard_json
                           │         │  更新 segment_urls
                           └─────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
        ┌─────────┐       ┌─────────┐       ┌─────────┐
        │本地文件 │       │  飞书   │       │ 前端UI  │
        └─────────┘       └─────────┘       └─────────┘
```

#### 详细步骤

1. **读取并更新 storyboard.json**
   - 更新 crucial、action、sound、negative_constraint
   - 重新构建完整 prompt

2. **保存到数据库**（优先）
   ```python
   task_service.save_storyboard(
       project_id=project_id,
       storyboards=storyboards,
       status="editing"
   )
   ```

3. **保存到本地文件**（同步）

4. **调用视频 API 重新生成**

5. **回写结果**
   - 数据库：更新 storyboard_json + segment_urls
   - 本地：更新视频文件 + 帧图片
   - 飞书：同步更新

#### API 端点

```
POST /api/batch/edit-and-regenerate
{
  "table_id": "tblXXX",
  "record_id": "recXXX",
  "project_id": "3242d9ae0752",
  "segment_index": 2,
  "crucial": "...",
  "action": "...",
  "sound": "...",
  "negative_constraint": "..."
}
```

---

### 3.4 级联重做（Cascade Redo）

#### 触发场景

用户希望从某一段开始，清空该段及所有后续段的视频数据，准备重新生成。

#### 流程图

```
┌─────────┐    ①指定起始段   ┌─────────┐
│  前端   │ ─────────────>  │  后端   │
│         │  from_segment=2 │         │
└─────────┘                 └─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        ┌─────────┐        ┌─────────┐        ┌─────────┐
        │备份旧文件│       │清空数据  │       │更新状态  │
        │history/ │        │段2-6    │        │→ ready  │
        └─────────┘        └─────────┘        └─────────┘
```

#### 详细步骤

1. **获取项目锁**（防止并发）

2. **备份旧文件到 history/ 目录**
   ```
   segments/segment_2_segment.mp4 → history/segment_2_20260128_120000.mp4
   frames/segment_2_*.jpg         → history/segment_2_*_20260128_120000.jpg
   ```

3. **清空从指定段开始的数据**
   - 删除本地视频文件和帧图片
   - 清空飞书 segment_X_video_url 字段

4. **可选：清空分镜脚本**
   - 如果勾选"同时重新生成分镜"
   - 清空从该段开始的 storyboard_json

5. **更新状态为 `storyboard_ready`**

6. **释放项目锁**

#### API 端点

```
POST /api/batch/cascade-redo
{
  "table_id": "tblXXX",
  "record_id": "recXXX",
  "from_segment_index": 2,
  "regenerate_storyboard": false
}
```

---

## 四、核心模块说明

### 4.1 数据库模型（BatchTask）

```python
class BatchTask(SQLModel, table=True):
    __tablename__ = "batch_tasks"
    
    id: int                          # 自增主键
    project_id: str                  # 项目唯一标识
    feishu_record_id: str            # 飞书记录 ID
    template_id: str                 # 模板类型
    publish_date: str                # 发布日期 (YYYYMMDD)
    storage_path: str                # 本地存储路径
    
    storyboard_json: str             # 分镜脚本 JSON
    segment_urls: str                # 视频生成结果 JSON
    
    status: str                      # 任务状态
    total_segments: int              # 总段数
    final_video_url: str             # 合并后的最终视频
    error_message: str               # 错误信息
    
    created_at: datetime
    updated_at: datetime
```

### 4.2 状态机

```
                    ┌─────────────┐
                    │   pending   │  初始状态
                    └──────┬──────┘
                           │ 生成分镜
                           ▼
                    ┌─────────────┐
                    │ storyboard  │  分镜就绪
                    │   _ready    │
                    └──────┬──────┘
                           │ 生成视频
                           ▼
                    ┌─────────────┐
                    │ generating  │  生成中（段N）
                    │ _segment_N  │
                    └──────┬──────┘
                           │ 完成/部分完成
                           ▼
              ┌────────────┴────────────┐
              ▼                         ▼
       ┌─────────────┐          ┌─────────────┐
       │ storyboard  │          │all_segments │  全部完成
       │   _ready    │          │   _ready    │
       └─────────────┘          └─────────────┘
```

### 4.3 核心服务

| 服务 | 文件 | 职责 |
|------|------|------|
| **FeishuBitableService** | `feishu_bitable.py` | 飞书多维表格 CRUD |
| **VideoSegmentService** | `video_segment_service.py` | 视频生成、下载、帧提取 |
| **TaskStatusService** | `task_status_service.py` | 数据库状态管理 |
| **ProjectPathService** | `project_path_service.py` | 项目路径解析 |
| **ProjectLockService** | `project_lock_service.py` | 并发控制 |

---

## 五、数据一致性保障

### 5.1 并发控制

**项目锁机制**：防止同一项目的多个操作同时执行

```python
# 获取锁
success, error = await lock_service.try_lock(project_id, operation="generate_segment_0")

# 操作完成后释放
await lock_service.release_lock(project_id)
```

**锁超时配置**：
| 操作 | 超时时间 |
|------|----------|
| generate_segment | 10 分钟 |
| cascade_redo | 10 分钟 |
| edit_regenerate | 10 分钟 |

### 5.2 数据同步策略

**写入顺序**：
1. 数据库（主数据源）
2. 本地文件（缓存/备份）
3. 飞书表格（协作展示）

**故障恢复**：
- 如果本地文件丢失：从数据库的在线 URL 重新下载
- 如果飞书同步失败：不影响主流程，下次同步时自动修复

### 5.3 自动同步机制

**`_auto_update_generated_videos` 函数**：

在以下时机触发：
- 连接飞书表格时
- 手动点击"同步数据库"时

执行逻辑：
1. 遍历数据库中所有项目
2. 对比本地 storyboard.json 和 segment_urls
3. 将数据库的权威数据同步到飞书

---

## 六、V2 架构重构（2026-01-29）

### 6.1 重构背景

原有架构中，segments 数据存在于多个位置，导致数据不一致问题：
- 数据库 `segment_urls`
- 数据库 `storyboard_json`
- 本地 `storyboard.json` 文件
- 飞书表格字段

读取时需要从多个来源合并数据，写入时需要同步多个位置，容易出现不一致。

### 6.2 新架构核心原则

**数据库 `segment_urls` 是 segments 数据的唯一事实来源**

```
┌────────────────────────────────────────────────────────────────┐
│                    数据库（唯一事实来源）                        │
│                                                                │
│  batch_tasks 表                                                │
│  ├── segment_urls: JSON  ← 视频URL、帧URL、状态（唯一读取源）   │
│  ├── storyboard_json: JSON  ← 分镜脚本内容（prompt配置）       │
│  └── status: String  ← 任务状态                                │
└────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ↓               ↓               ↓
         前端 API          飞书同步      本地文件系统
        (只读数据库)       (异步推送)    (视频/帧存储)
```

### 6.3 数据流改进

#### 写入流程（LLM 生成视频后）

```
LLM/视频 API 返回结果
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 下载视频到本地                                            │
│    ├── 保存到: /storage/projects/{pid}/segments/segment_X.mp4│
│    └── 提取帧到: /storage/projects/{pid}/frames/             │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 2.【第一落点】写入数据库 segment_urls                         │
│    segment_urls = {                                          │
│      "segment_X": {                                          │
│        "video_url": "/storage/projects/{pid}/segments/...",  │  ← 本地路径
│        "first_frame_url": "/storage/projects/{pid}/frames/...",
│        "last_frame_url": "/storage/projects/{pid}/frames/...",
│        "status": "completed",                                │
│        "updated_at": "2026-01-29T..."                        │
│      }                                                       │
│    }                                                         │
└─────────────────────────────────────────────────────────────┘
         │
         ├─────────────────────────────────────────────────────┐
         ▼                                                     ▼
┌───────────────────────┐                       ┌───────────────────────┐
│ 3. 更新本地文件（备份） │                       │ 4. 同步到飞书（异步）  │
│    storyboard.json    │                       │    segment_X_video_url│
└───────────────────────┘                       └───────────────────────┘
```

#### 读取流程（前端获取数据）

```
前端调用 /api/batch/tasks/local
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 后端直接从数据库读取 segment_urls                            │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ SELECT segment_urls FROM batch_tasks WHERE ...          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ 解析 segment_urls JSON，构建 segments 数组                   │
│ segments = [                                                 │
│   { videoUrl: "/storage/.../segment_0.mp4", status: "completed" },
│   { videoUrl: "/storage/.../segment_1.mp4", status: "completed" },
│   ...                                                        │
│ ]                                                            │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
    返回给前端
```

### 6.4 URL 统一使用本地路径

**改进前**：数据库可能存储云端 URL 或本地路径，混乱不一致
```
video_url: "https://midjourney-plus.oss-us-west-1.aliyuncs.com/flow/xxx.mp4"  ❌
```

**改进后**：统一使用本地路径，视频下载到本地后更新
```
video_url: "/storage/projects/{pid}/segments/segment_X_eating.mp4"  ✅
```

好处：
- 前端直接请求本地文件，无需依赖外部服务
- 重新生成后 URL 自动更新（文件名包含类型标识）
- 历史版本归档到 `archive/` 目录

### 6.5 关键代码变更

#### `parse_feishu_record_to_task` 简化

```python
# 改进前：从多个来源合并数据
segments = merge(db_segment_urls, local_storyboard, feishu_fields)

# 改进后：只从数据库 segment_urls 读取
if db_segment_urls:
    for i in range(segment_count):
        seg_key = f"segment_{i}"
        seg_data = db_segment_urls.get(seg_key, {})
        segments.append({
            "videoUrl": seg_data.get("video_url", ""),
            "status": seg_data.get("status", "pending"),
            ...
        })
```

#### `video_segment_service._download_and_extract_frames` 改进

```python
# 改进前：返回帧路径，video_url 使用云端 URL
return (first_frame_url, last_frame_url)

# 改进后：同时返回本地视频路径
local_video_url = f"/storage/projects/{project_id}/segments/{video_filename}"
return (first_frame_url, last_frame_url, local_video_url)
```

#### `edit_and_regenerate` 写入顺序

```python
# 改进后的写入顺序
# 1.【第一落点】更新数据库 segment_urls
task_service.update_segment_result(
    project_id=project_id,
    segment_index=segment_index,
    video_url=local_video_url,  # 本地路径
    status="completed"
)

# 2. 更新本地 storyboard.json（备份）
with open(storyboard_path, "w") as f:
    json.dump(storyboard_data, f)

# 3. 异步同步到飞书
```

### 6.6 历史数据归档

重新生成视频时，旧数据自动归档：

```
data/uploads/projects/{date}/{template}/{project_id}/
├── segments/
│   └── segment_2_eating.mp4        ← 当前版本
├── frames/
│   ├── segment_2_first.jpg
│   └── segment_2_last.jpg
└── archive/                        ← 历史版本
    └── segment_2/
        └── 20260129_084923/
            ├── segment_2_segment.mp4
            ├── segment_2_first.jpg
            └── segment_2_last.jpg
```

数据库中的 `segment_history` 字段记录归档历史：

```json
{
  "segment_2": [
    {
      "video_url": "/storage/.../archive/segment_2/20260129_084923/segment_2_segment.mp4",
      "archived_at": "2026-01-29T01:20:00.177198",
      "local_video_path": "data/.../archive/segment_2/20260129_084923/segment_2_segment.mp4"
    }
  ]
}
```

---

## 七、附录：字段说明

### 7.1 数据库字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `storyboard_json` | TEXT | 分镜脚本，包含 7 段的 prompt、status、video_url 等 |
| `segment_urls` | TEXT | 视频生成结果，每段的完整信息（权威数据源） |

### 7.2 storyboard_json 结构

```json
{
  "storyboards": [
    {
      "segment_index": 0,
      "segment_type": "intro",
      "crucial": "...",
      "action": "...",
      "sound": "...",
      "negative_constraint": "...",
      "prompt": "...(完整 prompt)...",
      "video_url": "https://...",
      "status": "completed",
      "first_frame_url": "/storage/projects/.../frames/segment_0_first.jpg",
      "last_frame_url": "/storage/projects/.../frames/segment_0_last.jpg"
    },
    // ... 共 7 段
  ],
  "total_segments": 7,
  "timestamp": "2026-01-28T12:00:00"
}
```

### 7.3 segment_urls 结构（V2 更新）

> **V2 重要变更**：`video_url` 统一使用本地路径，不再存储云端 URL

```json
{
  "segment_0": {
    "video_url": "/storage/projects/cfa572ef7db9/segments/segment_0_segment.mp4",
    "first_frame_url": "/storage/projects/cfa572ef7db9/frames/segment_0_first.jpg",
    "last_frame_url": "/storage/projects/cfa572ef7db9/frames/segment_0_last.jpg",
    "status": "completed",
    "updated_at": "2026-01-29T08:13:18.032335"
  },
  "segment_1": {
    "video_url": "/storage/projects/cfa572ef7db9/segments/segment_1_segment.mp4",
    "first_frame_url": "/storage/projects/cfa572ef7db9/frames/segment_1_first.jpg",
    "last_frame_url": "/storage/projects/cfa572ef7db9/frames/segment_1_last.jpg",
    "status": "completed",
    "updated_at": "2026-01-29T09:00:00.000000"
  },
  "segment_2": {
    "video_url": "",
    "status": "pending"
  }
  // ...
}
```

### 7.4 飞书表格字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `project_id` | 文本 | 项目唯一标识 |
| `opening_image_url` | 附件 | 宠物原始图片 |
| `template_id` | 文本 | 模板类型 |
| `release_date` | 日期 | 发布日期 |
| `storyboard_json` | 文本 | 分镜脚本 JSON |
| `segment_0_video_url` ~ `segment_6_video_url` | 文本 | 各段视频 URL |
| `final_video_url` | 文本 | 最终合并视频 |
| `status` | 文本 | 任务状态 |
| `error_message` | 文本 | 错误信息 |
| `updated_at` | 日期 | 最后更新时间 |

---

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 1.0 | 2026-01-28 | 初始版本，完整描述技术架构和数据流 |
| 2.0 | 2026-01-29 | **V2 架构重构**：数据库作为唯一事实来源，segments 只从 segment_urls 读取，video_url 统一使用本地路径，添加历史数据归档机制 |
