# PetForge 批量处理工坊 - 技术实现指南

> **版本**: 2.1  
> **更新日期**: 2026-01-27

---

## 一、系统架构

### 1.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PetForge 系统架构                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐                                                            │
│  │   用户浏览器  │                                                            │
│  │  (React App) │                                                            │
│  └──────┬──────┘                                                            │
│         │ HTTP                                                              │
│         ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        FastAPI 后端                                  │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │   │
│  │  │ batch.py    │  │ proxy.py    │  │ video.py    │  │ storage.py │ │   │
│  │  │ (批量处理)  │  │ (代理服务)  │  │ (视频接口) │  │ (存储服务) │ │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────┬──────┘ │   │
│  │         │                │                │               │        │   │
│  │         └────────────────┼────────────────┼───────────────┘        │   │
│  │                          ▼                                         │   │
│  │  ┌───────────────────────────────────────────────────────────────┐ │   │
│  │  │                      Services 业务层                          │ │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐│ │   │
│  │  │  │FeishuBitable │  │StoryboardSvc │  │VideoSegmentService   ││ │   │
│  │  │  │(飞书表格)    │  │(分镜生成)    │  │(视频段生成)          ││ │   │
│  │  │  └──────────────┘  └──────────────┘  └──────────────────────┘│ │   │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐│ │   │
│  │  │  │TaskStatusSvc │  │ProjectPathSvc│  │ProjectLockService    ││ │   │
│  │  │  │(状态管理)    │  │(路径服务)    │  │(并发锁)              ││ │   │
│  │  │  └──────────────┘  └──────────────┘  └──────────────────────┘│ │   │
│  │  └───────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│         │                │                │               │                │
│         ▼                ▼                ▼               ▼                │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐    ┌──────────┐           │
│  │ SQLite   │     │ 本地文件 │     │ DeepSeek │    │ VEO API  │           │
│  │ 数据库   │     │ 系统     │     │ LLM API  │    │ 视频生成 │           │
│  └──────────┘     └──────────┘     └──────────┘    └──────────┘           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 数据流向

```
用户操作 → 前端组件 → API 调用 → 路由处理 → 业务服务 → 数据存储
                                              ↓
                                         外部 API
                                      (LLM / VEO)
```

---

## 二、前端技术实现

### 2.1 状态管理

#### useReducer 架构

```typescript
// BatchPage.reducer.ts
type Action =
  | { type: 'SET_STATUS'; payload: PageStatus }
  | { type: 'SET_TASKS'; payload: BatchTask[] }
  | { type: 'SET_SELECTED_RECORDS'; payload: string[] }
  | { type: 'SET_STATUS_FILTER'; payload: StatusFilter }
  // ... 更多 action types

function pageReducer(state: PageState, action: Action): PageState {
  switch (action.type) {
    case 'SET_TASKS':
      return { ...state, tasks: action.payload }
    // ... 更多 case
  }
}
```

#### 状态结构

```typescript
// BatchPage.types.ts
interface PageState {
  status: PageStatus               // 页面加载状态
  feishuConfig: FeishuConfig       // 飞书配置
  tasks: BatchTask[]               // 任务列表
  selectedTaskId: string | null    // 当前选中的任务
  selectedRecordIds: string[]      // 多选的记录 ID
  statusFilter: StatusFilter       // 状态筛选
  showDetail: boolean              // 是否显示详情
  sidebarCollapsed: boolean        // 侧边栏折叠
  showBatchEditModal: boolean      // 批量编辑弹窗
  queueOpen: boolean               // 任务队列抽屉
  currentSegmentIndex: number      // 当前段索引
  settings: BatchSettings          // 设置
}
```

### 2.2 组件层次

```
BatchPage.tsx (主页面)
├── StatsBar.tsx (统计栏)
├── FeishuConfig.tsx (飞书配置)
├── TaskTable.tsx (任务列表)
│   ├── 表头（多选/排序）
│   ├── 筛选器
│   └── 任务行
├── TaskDetail.tsx (详情面板)
│   ├── 头部信息
│   ├── 首帧图片
│   ├── 分镜脚本
│   └── 分段预览
├── BatchPromptEditModal.tsx (批量编辑弹窗)
├── PromptEditModal.tsx (单个编辑弹窗)
└── ApiJobQueueDrawer.tsx (任务队列)
```

### 2.3 关键技术点

#### 多选优化

```typescript
// 使用 useCallback 避免无限循环
const handleSelectionChange = useCallback((ids: string[]) => {
  dispatch({ type: 'SET_SELECTED_RECORDS', payload: ids })
}, [])

// TaskTable 中使用
<TaskTable
  onSelectionChange={handleSelectionChange}
  // ...
/>
```

#### 弹窗层级处理

```typescript
// PromptEditModal.tsx - 使用 React Portal
import { createPortal } from 'react-dom'

return createPortal(
  <div className="fixed inset-0 z-[9999] ...">
    {/* 弹窗内容 */}
  </div>,
  document.body
)
```

#### 派生状态计算

```typescript
// 使用 useMemo 优化性能
const stats = useMemo(() => calculateStats(tasks), [tasks])
const filteredTasks = useMemo(() => 
  filterTasksByStatus(tasks, statusFilter), 
  [tasks, statusFilter]
)
```

---

## 三、后端技术实现

### 3.1 路由层 (batch.py)

#### 核心 API 实现

```python
# 连接飞书表格
@router.post("/connect-feishu")
async def connect_feishu(req: ConnectFeishuRequest):
    # 1. 验证飞书凭证
    service = FeishuBitableService(req.app_id, req.app_secret)
    
    # 2. 获取表格字段
    fields = await service.get_table_fields(req.app_token, req.table_id)
    
    # 3. 保存连接配置
    save_feishu_connection(req.table_id, {
        "app_token": req.app_token,
        "table_id": req.table_id,
        "app_id": req.app_id,
        "app_secret": req.app_secret
    })
    
    # 4. 加载记录并创建任务
    records = await service.get_all_records(req.app_token, req.table_id)
    # ...
```

#### 并发控制

```python
# 项目锁服务
from paretoai.services.project_lock_service import get_project_lock_service

lock_service = get_project_lock_service()

# 尝试获取锁
success, error_msg = await lock_service.try_lock(
    project_id=project_id,
    operation=f"generate_segment_{segment_index}",
    timeout=0  # 非阻塞
)

if not success:
    return {"success": False, "error": f"项目正在处理中: {error_msg}"}

try:
    # 执行操作
    ...
finally:
    # 释放锁
    await lock_service.release_lock(project_id)
```

### 3.2 服务层

#### FeishuBitableService

```python
# paretoai/services/feishu_bitable.py
class FeishuBitableService:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._tenant_access_token = None
    
    async def get_tenant_access_token(self) -> str:
        """获取租户 Token"""
        # ...
    
    async def get_all_records(self, app_token: str, table_id: str) -> List[Dict]:
        """获取表格所有记录"""
        # ...
    
    async def update_record(self, app_token: str, table_id: str, 
                           record_id: str, fields: Dict) -> Dict:
        """更新单条记录"""
        # ...
    
    async def upload_attachment_to_record(self, app_token: str, table_id: str,
                                          record_id: str, field_id: str,
                                          file_path: str, file_name: str) -> Dict:
        """上传附件到记录"""
        # ...
```

#### StoryboardService

```python
# paretoai/services/storyboard_service.py
class StoryboardService:
    def __init__(self):
        self.llm_client = self._init_llm_client()
    
    def generate_storyboard(self, opening_image_url: str, 
                           scene_description: str,
                           segment_count: int = 7) -> List[Dict]:
        """生成分镜脚本"""
        # 1. 加载提示词模板
        prompt_template = self._load_prompt_template()
        
        # 2. 构建完整提示词
        prompt = prompt_template.format(
            opening_image_url=opening_image_url,
            scene_description=scene_description,
            segment_count=segment_count
        )
        
        # 3. 调用 LLM
        response = self.llm_client.chat(prompt)
        
        # 4. 解析结果
        storyboards = self._parse_response(response)
        
        return storyboards
```

#### TaskStatusService

```python
# paretoai/services/task_status_service.py
class TaskStatusService:
    def update_task_status(self, project_id: str, status: str, 
                          progress: str = None, error_message: str = None):
        """更新任务状态"""
        with get_session() as session:
            task = session.query(BatchTask).filter(
                BatchTask.project_id == project_id
            ).first()
            
            if task:
                task.status = status
                if progress:
                    task.progress = progress
                if error_message is not None:
                    task.error_message = error_message
                task.updated_at = datetime.now()
                session.commit()
    
    def update_segment_result(self, project_id: str, segment_index: int,
                              video_url: str, first_frame: str, 
                              last_frame: str):
        """更新段生成结果"""
        with get_session() as session:
            task = session.query(BatchTask).filter(
                BatchTask.project_id == project_id
            ).first()
            
            # 更新 segment_urls JSON
            segment_urls = json.loads(task.segment_urls or '{}')
            segment_urls[f'segment_{segment_index}'] = {
                'status': 'completed',
                'video_url': video_url,
                'first_frame': first_frame,
                'last_frame': last_frame
            }
            task.segment_urls = json.dumps(segment_urls)
            
            # 更新状态（修复：不设为 generating_segment_X+1）
            completed_count = sum(
                1 for v in segment_urls.values() 
                if v.get('status') == 'completed'
            )
            if completed_count == task.total_segments:
                task.status = 'all_segments_ready'
            else:
                task.status = 'storyboard_ready'  # 等待用户推进
            
            session.commit()
```

### 3.3 数据模型

```python
# paretoai/models.py
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class BatchTask(SQLModel, table=True):
    __tablename__ = "batch_tasks"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: str = Field(max_length=50, unique=True, index=True)
    user_id: Optional[str] = Field(max_length=50)
    feishu_table_id: Optional[str] = Field(max_length=100)
    feishu_record_id: Optional[str] = Field(max_length=100)
    template_id: Optional[str] = Field(max_length=50)
    storage_path: Optional[str] = None
    status: str = Field(max_length=50, default="pending")
    progress: Optional[str] = Field(max_length=50)
    error_message: Optional[str] = None
    storyboard_json: Optional[str] = None  # JSON 字符串
    segment_urls: Optional[str] = None     # JSON 字符串
    final_video_url: Optional[str] = None
    total_segments: Optional[int] = Field(default=7)
    current_segment: Optional[int] = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    publish_date: Optional[str] = Field(max_length=20)
```

---

## 四、核心流程实现

### 4.1 分镜生成流程

```
┌─────────────────────────────────────────────────────────────────┐
│                      分镜生成流程                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  前端                     后端                      外部服务     │
│  ────                     ────                      ────────    │
│    │                        │                          │        │
│    │  POST /generate-storyboards                       │        │
│    │ ─────────────────────> │                          │        │
│    │                        │                          │        │
│    │                        │  1. 验证并发锁            │        │
│    │                        │  2. 下载首帧图片          │        │
│    │                        │                          │        │
│    │                        │  3. 调用 LLM             │        │
│    │                        │ ─────────────────────────>│        │
│    │                        │                          │        │
│    │                        │  4. 解析分镜结果          │<───────│
│    │                        │                          │        │
│    │                        │  5. 写入数据库            │        │
│    │                        │  6. 写入本地文件          │        │
│    │                        │  7. 同步飞书状态          │        │
│    │                        │                          │        │
│    │  <─────────────────── │  返回结果                 │        │
│    │                        │                          │        │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 视频段生成流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     视频段生成流程                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 获取项目锁                                                  │
│     └─> 检查是否有其他操作正在进行                               │
│                                                                 │
│  2. 获取输入帧                                                  │
│     ├─> 段0: 使用 opening_image.jpg                             │
│     └─> 段1-6: 使用 segment_{N-1}_last.jpg                      │
│                                                                 │
│  3. 获取分镜提示词                                              │
│     └─> 从数据库 storyboard_json 中读取                         │
│                                                                 │
│  4. 调用 VEO API                                                │
│     └─> 传入 input_image + motion_prompt                        │
│                                                                 │
│  5. 保存结果                                                    │
│     ├─> 保存视频: segments/segment_N_segment.mp4                │
│     ├─> 提取首帧: frames/segment_N_first.jpg                    │
│     └─> 提取尾帧: frames/segment_N_last.jpg                     │
│                                                                 │
│  6. 更新状态                                                    │
│     ├─> 数据库: segment_urls JSON                               │
│     ├─> 本地: meta.json                                         │
│     └─> 飞书: segment_N_video_url 字段                          │
│                                                                 │
│  7. 释放项目锁                                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 状态流转图

```
┌─────────────────────────────────────────────────────────────────┐
│                      任务状态流转                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  pending ───────────> storyboard_ready ───────────> completed   │
│    │                        │ ▲                         ▲       │
│    │                        │ │                         │       │
│    │   [连接飞书]           │ │ [生成成功/失败回退]     │       │
│    └──────────────────────> │ │                         │       │
│                             │ │                         │       │
│                             ▼ │                         │       │
│                    generating_segment_X                 │       │
│                             │                           │       │
│                             │ [所有段完成]              │       │
│                             ▼                           │       │
│                    all_segments_ready ──────────────────┘       │
│                             │         [合并视频]                 │
│                             │                                   │
│                             └──────> failed                     │
│                                      (可重试)                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、关键技术细节

### 5.1 四端数据一致性保证

```python
# 写入顺序（确保一致性）
async def save_segment_result(project_id, segment_index, video_url, ...):
    # 1. 写入数据库（主数据源，必须成功）
    task_service.update_segment_result(project_id, segment_index, ...)
    
    # 2. 写入本地文件（备份）
    try:
        write_meta_json(storage_path, status, progress)
    except Exception as e:
        logger.warning(f"写入本地文件失败: {e}")
    
    # 3. 同步飞书（通知，可失败）
    try:
        await feishu_service.update_record(app_token, table_id, record_id, {
            f"segment_{segment_index}_video_url": video_url,
            "status": status,
            "updated_at": feishu_date_now_ms()
        })
    except Exception as e:
        logger.warning(f"同步飞书失败: {e}")
```

### 5.2 错误处理与状态回退

```python
# 生成失败时的状态回退
except Exception as e:
    error_msg = str(e)
    
    # 关键修复：回退数据库状态
    task_service.update_task_status(
        project_id=project_id,
        status="storyboard_ready",  # 回退到等待状态
        error_message=error_msg
    )
    
    # 同步本地和飞书
    write_meta_json(storage_path, "storyboard_ready", error_msg)
    await feishu_service.update_record(..., {"status": "storyboard_ready"})
    
    return {"success": False, "error": error_msg}
```

### 5.3 V2 目录结构

```python
# paretoai/services/project_path_service.py
class ProjectPathService:
    def get_project_storage_path(self, project_id: str) -> str:
        """
        V2 目录结构: data/uploads/projects/{日期}/{模板}/{项目ID}
        """
        # 从数据库获取 publish_date 和 template_id
        task = self._get_task(project_id)
        
        date_str = task.publish_date or datetime.now().strftime('%Y-%m-%d')
        template_id = task.template_id or 'eating-template'
        
        return f"data/uploads/projects/{date_str}/{template_id}/{project_id}"
```

---

## 六、配置说明

### 6.1 环境变量

```bash
# .env
# LLM 配置
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# 数据库
DB_URL=sqlite:///./paretoai.db

# 存储
CLOUD_STORAGE_TYPE=local
LOCAL_STORAGE_PATH=./data/uploads
LOCAL_STORAGE_URL=http://localhost:8000/static/uploads
```

### 6.2 飞书配置

```json
// data/feishu_connections.json
{
  "table_id": {
    "app_token": "飞书应用 Token",
    "table_id": "多维表格 ID",
    "app_id": "应用 ID",
    "app_secret": "应用密钥",
    "drive_folder_token": "云盘文件夹 Token（可选）"
  }
}
```

---

## 七、调试与测试

### 7.1 常用调试命令

```bash
# 检查数据库状态
python scripts/inspect_db.py

# 验证四端一致性
python scripts/verify_all_data_consistency.py

# 比对飞书和数据库
python scripts/compare_feishu_and_db.py

# 迁移本地数据到数据库
python scripts/migrate_local_to_db.py
```

### 7.2 运行测试

```bash
# 运行 V2 集成测试
pytest tests/integration/test_batch_workshop_v2.py -v

# 运行单个测试
pytest tests/integration/test_batch_workshop_v2.py::test_generate_storyboard -v
```

---

## 八、已知限制与待优化

### 8.1 当前限制

| 限制 | 说明 | 影响 |
|-----|------|------|
| 单数据库 | SQLite 不支持高并发 | 需迁移到 PostgreSQL |
| 本地存储 | 不适合分布式部署 | 需迁移到云存储 |
| 无重试队列 | 飞书同步失败无自动重试 | 可能导致数据不一致 |

### 8.2 优化建议

1. **数据库**：生产环境使用 PostgreSQL
2. **存储**：使用阿里云 OSS 或 AWS S3
3. **队列**：添加 Celery + Redis 任务队列
4. **监控**：添加 Prometheus 指标

---

*文档更新时间: 2026-01-27*
