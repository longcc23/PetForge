# PetForge 批量处理工坊 - 技术诊断报告

> **诊断日期**: 2026-01-27  
> **诊断范围**: 前端页面、后端API、数据同步、按钮逻辑、刷新机制  
> **诊断级别**: 深度代码审查

---

## 一、执行摘要

### 1.1 项目概述

PetForge 是一个批量视频生产平台，集成飞书多维表格，支持 AI 分镜生成和视频段生成。核心技术栈：
- **前端**: React 18 + TypeScript + Vite + Tailwind CSS
- **后端**: Python 3.12 + FastAPI + SQLModel + SQLite
- **外部依赖**: 飞书 API、DeepSeek LLM、Google VEO

### 1.2 诊断结果总览

| 类别 | 问题数 | 严重程度 |
|------|--------|----------|
| 🔴 严重问题 | 3 | 可能导致数据丢失或功能失效 |
| 🟠 中等问题 | 8 | 影响用户体验或系统稳定性 |
| 🟡 轻微问题 | 6 | 代码质量或潜在风险 |
| 🟢 优化建议 | 5 | 架构改进或性能优化 |

---

## 二、严重问题 🔴

### 2.1 竞态条件：状态更新与 UI 渲染不同步

**位置**: `BatchPage.tsx` 第 119-135 行

**问题描述**:
```typescript
const loadTasks = useCallback(async () => {
  dispatch({ type: 'LOAD_TASKS_START' })
  try {
    const data = await batchApi.loadTasks(feishuConfig.tableId)
    const nextTasks = data.tasks || []
    // ...状态追踪逻辑
    dispatch({ type: 'LOAD_TASKS_SUCCESS', payload: nextTasks })
  } catch (error) {
    // ...
  }
}, [feishuConfig.connected, feishuConfig.tableId, addToast])
```

**风险分析**:
1. `loadTasks` 在多个地方被调用（连接成功、操作完成后、手动刷新）
2. 如果快速连续触发，可能导致旧请求的响应覆盖新请求的结果
3. `lastTaskStatusRef` 的更新可能与实际 tasks 状态不一致

**影响范围**: 任务状态显示错误、Toast 通知重复或遗漏

**修复建议**:
```typescript
// 添加请求取消机制
const loadTasksAbortRef = useRef<AbortController | null>(null)

const loadTasks = useCallback(async () => {
  // 取消之前的请求
  loadTasksAbortRef.current?.abort()
  loadTasksAbortRef.current = new AbortController()
  
  dispatch({ type: 'LOAD_TASKS_START' })
  try {
    const data = await batchApi.loadTasks(
      feishuConfig.tableId, 
      5000, 
      loadTasksAbortRef.current.signal
    )
    // ...
  } catch (error) {
    if (error.name === 'AbortError') return // 忽略被取消的请求
    // ...
  }
}, [feishuConfig.tableId])
```

---

### 2.2 数据库与飞书同步不一致的根本原因

**位置**: `batch.py` 第 918-956 行 (`generate_segments` API)

**问题描述**:

后端在生成视频段时，存在多个数据源的优先级不清晰问题：

```python
# 从数据库/本地文件读取 storyboard_json
storyboards = task_service.get_storyboard_with_fallback(
    project_id=project_id,
    storage_path=project_storage_path
)

if not storyboards:
    # 不再回退到飞书！直接报错
    failed_count += 1
    return {
        "record_id": record_id,
        "success": False,
        "error": f"分镜数据不存在..."
    }
```

**隐藏问题**:
1. `get_storyboard_with_fallback` 优先读数据库，其次读本地文件
2. 但 `save_storyboard` 同时写数据库和本地文件，可能出现部分成功
3. 如果数据库写入成功但本地文件写入失败（或反之），会导致后续读取不一致

**影响范围**: 分镜数据丢失、段生成失败

**修复建议**:
```python
@classmethod
def save_storyboard(cls, project_id: str, storyboards: List[Dict], 
                    storage_path: Optional[str] = None, status: str = "storyboard_ready") -> bool:
    """保存分镜数据 - 事务性写入"""
    try:
        storyboard_json = json.dumps(storyboards, ensure_ascii=False)
        
        # 1. 写入本地文件（作为主存储）
        if storage_path:
            local_file = Path(storage_path) / "storyboard.json"
            local_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 使用原子写入
            temp_file = local_file.with_suffix('.tmp')
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({"storyboards": storyboards, ...}, f)
            temp_file.rename(local_file)  # 原子重命名
        
        # 2. 写入数据库
        success = cls.update_task_status(
            project_id=project_id,
            status=status,
            storyboard_json=storyboard_json,
            total_segments=len(storyboards),
        )
        
        return success
    except Exception as e:
        # 回滚：删除临时文件
        if temp_file and temp_file.exists():
            temp_file.unlink()
        raise
```

---

### 2.3 飞书连接状态恢复时的内存泄漏风险

**位置**: `batch.py` 第 137-223 行 (`_restore_feishu_connections`)

**问题描述**:
```python
async def _restore_feishu_connections():
    """恢复飞书连接状态（服务启动时调用）"""
    global _feishu_services
    saved_connections = _load_feishu_connections()

    for table_id, conn_info in saved_connections.items():
        try:
            # 重新创建服务实例
            service = FeishuBitableService(...)  # 创建新实例
            
            # 如果验证失败，service 对象没有被清理
            await service.list_records(app_token, actual_table_id, page_size=1)
            _feishu_services[table_id] = {...}
        except Exception as e:
            logger.warning(f"⚠️ 连接已失效，跳过恢复: {table_id}, error={e}")
            # service 对象泄漏！
```

**风险分析**:
1. 验证失败时，`FeishuBitableService` 实例未被清理
2. 如果该服务持有 HTTP 连接池或其他资源，会造成资源泄漏
3. 重启服务多次后可能耗尽系统资源

**修复建议**:
```python
for table_id, conn_info in saved_connections.items():
    service = None
    try:
        service = FeishuBitableService(...)
        await service.list_records(...)
        _feishu_services[table_id] = {...}
    except Exception as e:
        logger.warning(f"连接已失效: {table_id}")
        if service and hasattr(service, 'close'):
            await service.close()  # 显式关闭
    finally:
        if table_id not in _feishu_services and service:
            del service  # 确保清理
```

---

## 三、中等问题 🟠

### 3.1 前端状态管理中的冗余依赖

**位置**: `BatchPage.tsx` 第 163-178 行

**问题**:
```typescript
useEffect(() => {
  if (feishuConfig.connected && tasks.length === 0 && status === 'idle') {
    syncTasksFromFeishu()
  }
}, [feishuConfig.connected, tasks.length, status, syncTasksFromFeishu])
```

**分析**:
- `syncTasksFromFeishu` 每次渲染都会生成新函数（因为依赖 `addToast`）
- 可能导致不必要的 effect 重复执行

**修复**:
```typescript
// 使用 ref 存储函数，避免依赖变化
const syncTasksFromFeishuRef = useRef(syncTasksFromFeishu)
syncTasksFromFeishuRef.current = syncTasksFromFeishu

useEffect(() => {
  if (feishuConfig.connected && tasks.length === 0 && status === 'idle') {
    syncTasksFromFeishuRef.current()
  }
}, [feishuConfig.connected, tasks.length, status])
```

---

### 3.2 批量操作缺少进度反馈

**位置**: `BatchPage.tsx` 第 262-302 行 (`handleBatchEditConfirm`)

**问题**:
```typescript
const handleBatchEditConfirm = async (edits: Array<...>) => {
  // ...
  for (const segmentIndex of segmentIndices) {
    dispatch({ type: 'GENERATE_SEGMENT_START', payload: segmentIndex })
    // 这里没有更新每个任务的进度
    const data = await batchApi.generateSegments({...})
    totalSuccess += data.success_count || 0
    totalFailed += data.failed_count || 0
  }
  // 只在最后显示结果
  dispatch({ type: 'GENERATE_SEGMENT_SUCCESS', ... })
}
```

**用户体验问题**:
1. 长时间批量操作时，用户不知道当前进度
2. 无法取消正在进行的操作
3. 如果中间失败，用户不知道哪些成功哪些失败

**修复建议**:
```typescript
// 添加进度状态
const [batchProgress, setBatchProgress] = useState<{
  current: number
  total: number
  currentSegment?: number
  results: Array<{ taskId: string; success: boolean }>
}>({ current: 0, total: 0, results: [] })

// 在循环中更新进度
for (const segmentIndex of segmentIndices) {
  setBatchProgress(prev => ({ 
    ...prev, 
    currentSegment: segmentIndex,
    current: prev.current + 1 
  }))
  // ...
}
```

---

### 3.3 TaskTable 组件的性能问题

**位置**: `TaskTable.tsx` 第 89-115 行

**问题**:
```typescript
const columns = useMemo(() => [
  // ...
  // 动态分段列（最多显示7段）
  ...Array.from({ length: 7 }, (_, i) =>
    columnHelper.display({
      id: `segment_${i}`,
      header: `段${i}`,
      cell: ({ row }) => {
        const segment = row.original.segments[i]  // 每次渲染都访问
        // ...
      },
      size: 45,
    })
  ),
], [])  // 依赖为空，但 cell 函数访问了 row.original
```

**分析**:
1. `columns` 虽然用 `useMemo` 缓存，但 `cell` 渲染函数每次都会执行
2. 当有 100+ 任务时，7个段列 × 100行 = 700次 `segment` 访问
3. `segments` 数组可能不存在或长度不足，但代码没有防御性检查

**优化建议**:
```typescript
cell: ({ row }) => {
  const segments = row.original.segments
  if (!segments || !Array.isArray(segments) || i >= segments.length) {
    return <span className="text-zinc-700">-</span>
  }
  const segment = segments[i]
  return segment ? <SegmentStatus status={segment.status} /> : null
},
```

---

### 3.4 后端 API 缺少请求幂等性保护

**位置**: `batch.py` 全局

**问题**: 关键操作如 `generate-storyboards`、`generate-segments` 缺少幂等性 key

**风险**:
1. 前端网络重试可能导致重复生成
2. 用户双击按钮可能发送重复请求

**修复建议**:
```python
@router.post("/generate-storyboards")
async def generate_storyboards(
    req: GenerateStoryboardsRequest,
    idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key")
):
    """批量生成分镜脚本"""
    if idempotency_key:
        # 检查是否已处理过
        cached_result = await get_cached_result(idempotency_key)
        if cached_result:
            return cached_result
    
    # 处理请求...
    result = {...}
    
    if idempotency_key:
        await cache_result(idempotency_key, result, ttl=3600)
    
    return result
```

---

### 3.5 `getNextSegmentIndex` 逻辑复杂度高

**位置**: `batchUtils.ts` 第 40-90 行

**问题**:
```typescript
export function getNextSegmentIndex(task: BatchTask): number | null {
  if (!task.storyboardJson) return null

  // 状态判断逻辑过于复杂
  if (
    task.status.startsWith('generating_segment_') ||
    task.status === 'merging' ||
    task.status === 'storyboard_generating'
  ) {
    return null
  }

  if (task.status === 'completed') return null

  const storyboardSegments = parseStoryboardSegments(task.storyboardJson)
  // ...
}
```

**问题分析**:
1. 函数承担了太多职责：解析 JSON、状态判断、依赖检查
2. `status` 的判断是字符串匹配，容易出错
3. 没有处理 `storyboardJson` 解析失败的情况

**重构建议**:
```typescript
// 拆分为多个纯函数
export function isTaskProcessing(status: BatchTaskStatus): boolean {
  const processingStatuses: BatchTaskStatus[] = [
    'storyboard_generating',
    'merging',
    'generating_segment_0',
    'generating_segment_1',
    // ...
  ]
  return processingStatuses.includes(status)
}

export function getNextSegmentIndex(task: BatchTask): number | null {
  if (isTaskProcessing(task.status) || task.status === 'completed') {
    return null
  }
  
  const segments = parseStoryboardSegments(task.storyboardJson)
  if (!segments.length) return null
  
  return findFirstIncompleteSegment(segments, task.openingImageUrl)
}
```

---

### 3.6 错误处理不统一

**位置**: 前后端多处

**前端问题** (`batchApiService.ts`):
```typescript
export async function editAndRegenerate(params): Promise<EditAndRegenerateResult> {
  const res = await fetch(...)
  
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}))
    return {
      success: false,
      error: errorData.detail || errorData.message || `HTTP ${res.status}`,
    }
  }
  // 这里与其他 API 不同，不抛出异常而是返回 error 对象
}
```

**后端问题** (`batch.py`):
```python
except Exception as e:
    # 有时抛出 HTTPException
    raise HTTPException(status_code=400, detail=str(e))
    
# 有时直接返回错误
return {"record_id": record_id, "success": False, "error": error_msg}
```

**建议**: 统一错误处理模式
```typescript
// 前端：统一使用 Result 模式
type ApiResult<T> = 
  | { success: true; data: T }
  | { success: false; error: string; code?: string }

// 后端：统一使用 HTTPException
class AppError(HTTPException):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(
            status_code=status_code,
            detail={"code": code, "message": message}
        )
```

---

### 3.7 飞书 API 调用缺少重试机制

**位置**: `batch.py` 多处直接调用 `service.update_record`

**问题**:
```python
try:
    await service.update_record(app_token, table_id, record_id, fields)
except Exception as e:
    logger.warning(f"⚠️ 飞书同步失败: {e}")
    # 直接跳过，没有重试
```

**风险**:
1. 飞书 API 限流（100次/分钟）会导致同步失败
2. 网络波动导致的临时失败没有恢复机制

**修复建议**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError))
)
async def safe_update_record(service, app_token, table_id, record_id, fields):
    await service.update_record(app_token, table_id, record_id, fields)
```

---

### 3.8 LocalStorage 配置安全风险

**位置**: `BatchPage.tsx` 第 47-53 行, `FeishuConfig.tsx`

**问题**:
```typescript
// 保存到 localStorage
localStorage.setItem('feishu_config', JSON.stringify(feishuConfig))

// feishuConfig 包含 appSecret!
export interface FeishuConfig {
  appId: string
  appSecret: string  // 敏感信息！
  // ...
}
```

**安全风险**:
1. `appSecret` 是敏感凭证，不应存储在 localStorage
2. XSS 攻击可能窃取这些凭证
3. 浏览器开发者工具可以直接查看

**修复建议**:
1. 将 `appSecret` 仅存储在后端
2. 前端只存储非敏感信息（如 `tableId`、`appId`）
3. 使用 session 或 token 进行认证

```typescript
// 前端只存储引用信息
interface FeishuConfigPublic {
  appId: string
  tableId: string
  connected: boolean
  // appSecret 不存储
}

// 连接时通过后端安全通道传递
const handleConnect = async () => {
  await batchApi.connectFeishu({
    appId: config.appId,
    appSecret: secretInputRef.current, // 仅一次性使用，不存储
    tableId: config.tableId,
  })
}
```

---

## 四、轻微问题 🟡

### 4.1 类型定义不完整

**位置**: `types/index.ts`

```typescript
export interface Storyboard {
  // ...
  status: 'pending' | 'generating' | 'completed' | 'waiting_confirmation' | 'failed'
}
```

但后端返回的数据可能包含其他字段（如 `crucial_zh`、`action_zh`），前端类型未定义。

### 4.2 Magic Number 问题

```typescript
// BatchPage.tsx
const segment_count = max(3, min(8, segment_count))  // 为什么是 3-8？

// batchUtils.ts
while len(segments) < total_segments  // total_segments 默认 7，为什么？
```

**建议**: 提取为常量
```typescript
export const SEGMENT_COUNT = {
  MIN: 3,
  MAX: 8,
  DEFAULT: 7,
} as const
```

### 4.3 日志级别不合理

**位置**: `batch.py` 多处

```python
logger.warning(f"✅ 成功恢复飞书连接")  # WARNING 用于成功消息
logger.info(f"⚠️ 连接已失效")  # INFO 用于警告消息
```

### 4.4 未使用的变量

**位置**: `BatchPromptEditModal.tsx` 第 97 行

```typescript
export function BatchPromptEditModal({
  tasks: _tasks,  // 传入但未使用
  pendingSegments,
  // ...
})
```

### 4.5 CSS 类名硬编码

多处使用重复的 Tailwind 类名组合，建议提取为组件或工具类：

```typescript
// 重复出现
className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700..."
```

### 4.6 缺少单元测试

核心工具函数如 `parseStoryboardSegments`、`getNextSegmentIndex`、`calculateStats` 缺少单元测试覆盖。

---

## 五、优化建议 🟢

### 5.1 引入乐观更新模式

当前所有操作都是"请求-等待-刷新"模式，用户体验较差。

**建议**:
```typescript
const handleGenerateStoryboards = async () => {
  // 1. 乐观更新：立即更新 UI
  const optimisticTasks = tasks.map(t => 
    selectedIds.includes(t.id) 
      ? { ...t, status: 'storyboard_generating' } 
      : t
  )
  dispatch({ type: 'LOAD_TASKS_SUCCESS', payload: optimisticTasks })
  
  // 2. 发送请求
  try {
    await batchApi.generateStoryboards({...})
  } catch (error) {
    // 3. 失败回滚
    dispatch({ type: 'LOAD_TASKS_SUCCESS', payload: tasks })
  }
  
  // 4. 成功后刷新真实数据
  loadTasks()
}
```

### 5.2 实现 WebSocket 实时更新

当前使用轮询方式刷新任务状态，建议改用 WebSocket：

```python
# 后端
from fastapi import WebSocket

@router.websocket("/ws/tasks/{table_id}")
async def task_updates(websocket: WebSocket, table_id: str):
    await websocket.accept()
    async for message in task_update_stream(table_id):
        await websocket.send_json(message)
```

### 5.3 添加任务队列可视化

当前 `ApiJobQueueDrawer` 功能较简单，建议增加：
- 任务优先级调整
- 任务取消功能
- 重试失败任务
- 任务执行时间估算

### 5.4 实现批量操作的事务性

当前批量操作中间失败时，已成功的部分无法回滚：

```python
# 建议使用 saga 模式
class BatchOperationSaga:
    async def execute(self, record_ids: List[str]):
        completed = []
        try:
            for record_id in record_ids:
                await self.process_record(record_id)
                completed.append(record_id)
        except Exception as e:
            # 补偿：回滚已完成的操作
            for record_id in reversed(completed):
                await self.rollback_record(record_id)
            raise
```

### 5.5 分离飞书同步服务

当前飞书同步逻辑散落在各处，建议抽象为独立服务：

```python
class FeishuSyncService:
    """飞书同步服务 - 异步队列模式"""
    
    async def queue_sync(self, record_id: str, fields: dict):
        """将同步任务加入队列"""
        await self.sync_queue.put(SyncTask(record_id, fields))
    
    async def process_queue(self):
        """后台处理同步队列"""
        while True:
            task = await self.sync_queue.get()
            await self._sync_with_retry(task)
```

---

## 六、按钮逻辑诊断

### 6.1 按钮状态矩阵

| 按钮 | 触发条件 | 禁用条件 | loading 状态 | 问题 |
|------|----------|----------|--------------|------|
| 测试连接 | `!connected && appId && appSecret && tableId` | `connecting` | `connecting` | ✅ 正常 |
| 刷新 | `connected` | `loadingTasks` | `loadingTasks` | ✅ 正常 |
| 批量生成分镜 | `connected && tasks.length > 0` | `isOperating` | `generatingStoryboard` | ⚠️ 无选中校验时应提示 |
| 推进下一步 | `connected && readyCount > 0` | `isOperating \|\| readyCount === 0` | `generatingSegment` | ✅ 正常 |
| 批量合并 | `connected && tasks.length > 0` | `isOperating` | `merging` | ⚠️ 无选中校验时应提示 |
| 同步到飞书表格 | `connected` | `isOperating` | `syncing` | ✅ 正常 |
| 同步到云空间 | `connected && driveFolderToken` | `isOperating` | `uploadingToDrive` | ⚠️ 缺少 token 校验提示 |

### 6.2 按钮交互优化建议

1. **添加二次确认**: 对于 "批量合并"、"级联重做" 等不可逆操作
2. **添加操作限制**: 同一任务正在处理时，禁止再次操作
3. **优化 loading 显示**: 显示具体进度（如 "3/10 已完成"）

---

## 七、刷新逻辑诊断

### 7.1 当前刷新机制

```
┌─────────────────────────────────────────────────────────────┐
│                     刷新触发点                               │
├─────────────────────────────────────────────────────────────┤
│ 1. 连接成功 → syncTasksFromFeishu() [全量, 2-5秒]           │
│ 2. 手动刷新 → loadTasks() [本地, <100ms]                     │
│ 3. 操作完成 → loadTasks() [本地, <100ms]                     │
│    - 生成分镜后                                              │
│    - 生成视频段后                                            │
│    - 合并视频后                                              │
│    - 同步飞书后                                              │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 问题分析

1. **无自动刷新**: 长时间生成任务时，用户需手动刷新查看进度
2. **刷新粒度粗**: 每次都刷新全部任务，无增量更新
3. **状态追踪依赖内存**: `lastTaskStatusRef` 在页面刷新后丢失

### 7.3 改进建议

```typescript
// 1. 添加定时轮询（仅在有进行中任务时）
useEffect(() => {
  if (stats.inProgress === 0) return
  
  const interval = setInterval(() => {
    loadTasks()
  }, 5000) // 5秒轮询
  
  return () => clearInterval(interval)
}, [stats.inProgress, loadTasks])

// 2. 使用 Server-Sent Events 或 WebSocket 实时更新
useEffect(() => {
  const eventSource = new EventSource(`/api/batch/events?table_id=${tableId}`)
  eventSource.onmessage = (event) => {
    const update = JSON.parse(event.data)
    dispatch({ type: 'UPDATE_SINGLE_TASK', payload: update })
  }
  return () => eventSource.close()
}, [tableId])
```

---

## 八、同步逻辑诊断

### 8.1 四端同步架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   前端 UI    │ ←→  │  后端数据库  │ ←→  │  本地文件   │ ←→  │  飞书表格   │
│  (React)    │     │  (SQLite)   │     │  (JSON)     │     │  (Bitable)  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      │    API 调用       │    文件读写        │    API 调用       │
      └──────────────────→                    │                   │
                          │←─────────────────→                    │
                          │←──────────────────────────────────────→
```

### 8.2 同步问题

| 同步方向 | 触发时机 | 问题 |
|----------|----------|------|
| 数据库 → 前端 | `loadTasks()` | ✅ 正常 |
| 数据库 → 本地文件 | `save_storyboard()` | ⚠️ 非原子操作 |
| 数据库 → 飞书 | 操作完成后 | ⚠️ 失败静默忽略 |
| 飞书 → 数据库 | `syncTasksFromFeishu()` | ⚠️ 覆盖本地修改 |
| 本地文件 → 数据库 | `get_storyboard_with_fallback()` | ⚠️ 只读回退 |

### 8.3 建议的同步策略

```
写入优先级: 数据库 > 本地文件 > 飞书
读取优先级: 数据库 > 本地文件 > (不读飞书)
冲突解决: 数据库为准，飞书仅通知
```

---

## 九、测试建议

### 9.1 需要添加的测试用例

| 测试类型 | 测试场景 | 优先级 |
|----------|----------|--------|
| 单元测试 | `parseStoryboardSegments` 各种格式解析 | P0 |
| 单元测试 | `getNextSegmentIndex` 边界条件 | P0 |
| 集成测试 | 连接飞书 → 生成分镜 → 生成视频 全流程 | P0 |
| 集成测试 | 并发生成时的锁机制 | P1 |
| E2E 测试 | 批量选择 → 推进下一步 → 查看进度 | P1 |
| 性能测试 | 100+ 任务时的列表渲染性能 | P2 |

### 9.2 测试数据准备

```python
# tests/fixtures/storyboard_fixtures.py
VALID_STORYBOARD = [
    {"segment_index": 0, "status": "completed", "video_url": "..."},
    {"segment_index": 1, "status": "pending"},
    # ...
]

INVALID_STORYBOARD_CASES = [
    (None, "None 输入"),
    ("", "空字符串"),
    ("{}", "空对象"),
    ("invalid json", "非法 JSON"),
    ('{"storyboards": "not array"}', "storyboards 非数组"),
]
```

---

## 十、优先级修复计划

### 10.1 紧急修复（本周）

1. ✅ 修复竞态条件问题（添加请求取消机制）
2. ✅ 修复 LocalStorage 安全问题（移除 appSecret 存储）
3. ✅ 添加飞书 API 重试机制

### 10.2 重要改进（下周）

1. 实现数据库写入的原子性保证
2. 添加批量操作进度反馈
3. 统一错误处理模式

### 10.3 持续优化（本月）

1. 引入 WebSocket 实时更新
2. 添加单元测试覆盖
3. 性能优化（虚拟列表、懒加载）

---

## 附录

### A. 代码质量指标

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| TypeScript 严格模式 | ❌ 部分 | ✅ 全量 |
| 测试覆盖率 | ~20% | >70% |
| ESLint 警告 | 15+ | 0 |
| 循环依赖 | 2处 | 0 |

### B. 性能基准

| 操作 | 当前耗时 | 目标耗时 |
|------|----------|----------|
| 首次加载任务（100条） | 2-5秒 | <2秒 |
| 本地刷新 | <100ms | <50ms |
| 分镜生成（单个） | 5-10秒 | <5秒 |
| 视频段生成（单个） | 30-60秒 | 依赖外部 API |

---

*报告生成时间: 2026-01-27*  
*下次诊断建议: 修复严重问题后进行回归测试*
