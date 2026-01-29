/**
 * 批量处理工坊 API 服务层
 * 将所有与后端 /api/batch 的交互封装在此，与 UI 组件解耦
 */

import type { BatchTask } from '@/types'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// ========== 类型定义 ==========

export interface ConnectFeishuParams {
  appId: string
  appSecret: string
  tableId: string
  appToken?: string
  tenantAccessToken?: string
  driveFolderToken?: string
}

export interface ConnectFeishuResult {
  table_name: string
  record_count: number
  drive_folder_token?: string
}

export interface SavedConnection {
  table_id: string
  app_id: string
  app_secret: string
  app_token?: string
  drive_folder_token?: string
}

export interface LoadTasksResult {
  tasks: BatchTask[]
}

export interface GenerateStoryboardsParams {
  tableId: string
  recordIds: string[]
  concurrency: number
}

export interface GenerateStoryboardsResult {
  success_count: number
  failed_count: number
}

export interface GenerateSegmentsParams {
  tableId: string
  recordIds: string[]
  segmentIndex: number
  concurrency: number
}

export interface GenerateSegmentsResult {
  success_count: number
  failed_count: number
}

export interface MergeVideosParams {
  tableId: string
  recordIds: string[]
}

export interface MergeVideosResult {
  success_count: number
  failed_count: number
}

export interface RetryTaskParams {
  tableId: string
  recordId: string
  action: 'storyboard' | 'segment' | 'merge'
  segmentIndex?: number
}

export interface BatchSavePromptsItem {
  record_id: string
  project_id: string
  segment_index: number
  crucial: string
  action: string
  sound: string
  negative_constraint: string
  crucial_zh?: string
  action_zh?: string
  sound_zh?: string
  negative_constraint_zh?: string
  is_modified: boolean
}

export interface EditAndRegenerateParams {
  tableId: string
  recordId: string
  projectId: string
  segmentIndex: number
  crucial: string
  action: string
  sound: string
  negative_constraint: string
  crucial_zh?: string
  action_zh?: string
  sound_zh?: string
  negative_constraint_zh?: string
}

export interface EditAndRegenerateResult {
  success: boolean
  accepted?: boolean
  video_url?: string
  error?: string
  prompt_sent?: string
}

export interface CascadeRedoParams {
  tableId: string
  recordId: string
  fromSegmentIndex: number
  regenerateStoryboard: boolean
}

export interface CascadeRedoResult {
  cleared_segments: number[]
  backup_paths: string[]
}

export interface SyncToDriveParams {
  tableId: string
  projectIds: string[]
  projectPublishDates: Record<string, string>
  folderToken: string
}

export interface SyncToDriveResult {
  success: number
  total: number
  failed: number
}

// ========== API 函数 ==========

/**
 * 连接飞书表格
 */
export async function connectFeishu(params: ConnectFeishuParams): Promise<ConnectFeishuResult> {
  const res = await fetch(`${API_BASE}/api/batch/connect-feishu`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      app_id: params.appId,
      app_secret: params.appSecret,
      table_id: params.tableId,
      app_token: params.appToken || undefined,
      tenant_access_token: params.tenantAccessToken || undefined,
      drive_folder_token: params.driveFolderToken || undefined,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '连接失败')
  }

  return res.json()
}

/**
 * 获取已保存的连接列表
 */
export async function getSavedConnections(): Promise<{ connections: SavedConnection[] }> {
  const res = await fetch(`${API_BASE}/api/batch/saved-connections`)
  if (!res.ok) {
    throw new Error('获取保存的连接失败')
  }
  return res.json()
}

/**
 * 获取连接详情
 */
export async function getConnectionDetail(tableId: string): Promise<SavedConnection> {
  const res = await fetch(`${API_BASE}/api/batch/connection/${tableId}`)
  if (!res.ok) {
    throw new Error('获取连接详情失败')
  }
  return res.json()
}

/**
 * 加载任务列表（从本地数据库，快速）
 * 
 * 这是日常刷新使用的接口，不调用飞书API，响应时间 < 100ms
 */
export async function loadTasks(tableId: string, timeoutMs: number = 5000): Promise<LoadTasksResult> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    // 使用本地接口，从数据库读取（快速）
    const res = await fetch(`${API_BASE}/api/batch/tasks/local?table_id=${tableId}`, {
      signal: controller.signal,
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}))
      const errorMsg = errorData.detail || '加载任务失败'
      throw new Error(errorMsg)
    }

    return res.json()
  } catch (error) {
    clearTimeout(timeoutId)
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('请求超时，请检查网络连接或重试')
    }
    throw error
  }
}

/**
 * 全量同步任务列表（从飞书，较慢）
 * 
 * 仅在需要同步飞书新增记录时使用，响应时间 2-5 秒
 */
export async function syncTasksFromFeishu(tableId: string, timeoutMs: number = 30000): Promise<LoadTasksResult> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    // 使用全量同步接口，从飞书读取（慢）
    const res = await fetch(`${API_BASE}/api/batch/tasks?table_id=${tableId}`, {
      signal: controller.signal,
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}))
      const errorMsg = errorData.detail || '同步任务失败'
      throw new Error(errorMsg)
    }

    return res.json()
  } catch (error) {
    clearTimeout(timeoutId)
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('同步超时，请检查网络连接或重试')
    }
    throw error
  }
}

/**
 * 批量生成分镜
 */
export async function generateStoryboards(params: GenerateStoryboardsParams): Promise<GenerateStoryboardsResult> {
  const res = await fetch(`${API_BASE}/api/batch/generate-storyboards`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_ids: params.recordIds,
      concurrency: params.concurrency,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '生成分镜失败')
  }

  return res.json()
}

/**
 * 批量生成视频段
 */
export async function generateSegments(params: GenerateSegmentsParams): Promise<GenerateSegmentsResult> {
  const res = await fetch(`${API_BASE}/api/batch/generate-segments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_ids: params.recordIds,
      segment_index: params.segmentIndex,
      concurrency: params.concurrency,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '生成视频段失败')
  }

  return res.json()
}

/**
 * 批量合并视频
 */
export async function mergeVideos(params: MergeVideosParams): Promise<MergeVideosResult> {
  const res = await fetch(`${API_BASE}/api/batch/merge-videos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_ids: params.recordIds,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '合并视频失败')
  }

  return res.json()
}

/**
 * 同步视频到飞书表格
 */
export async function syncVideos(tableId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/batch/sync-videos?table_id=${tableId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '同步失败')
  }
}

/**
 * 同步项目到飞书云空间
 */
export async function syncToDrive(params: SyncToDriveParams): Promise<SyncToDriveResult> {
  const res = await fetch(`${API_BASE}/api/batch/sync-to-drive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      project_ids: params.projectIds,
      project_publish_dates: params.projectPublishDates,
      folder_token: params.folderToken,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '同步到云空间失败')
  }

  return res.json()
}

/**
 * 重试单个任务
 */
export async function retryTask(params: RetryTaskParams): Promise<void> {
  const res = await fetch(`${API_BASE}/api/batch/retry-task`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_id: params.recordId,
      action: params.action,
      segment_index: params.segmentIndex,
    }),
  })

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}))
    const errorMsg = errorData.detail || errorData.message || `HTTP ${res.status}: ${res.statusText}`
    throw new Error(errorMsg)
  }
}

/**
 * 上传首帧图片
 */
export async function uploadImage(tableId: string, recordId: string, file: File): Promise<void> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('table_id', tableId)
  formData.append('record_id', recordId)

  const res = await fetch(`${API_BASE}/api/batch/upload-image`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '上传失败')
  }
}

/**
 * 批量保存提示词
 */
export async function batchSavePrompts(tableId: string, items: BatchSavePromptsItem[]): Promise<{
  success_count: number
  failed_count: number
  results: Array<{ record_id: string; success: boolean; error?: string }>
}> {
  const res = await fetch(`${API_BASE}/api/batch/batch-save-prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: tableId,
      items,
    }),
  })

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}))
    throw new Error(errorData.detail || '保存编辑失败')
  }

  return res.json()
}

/**
 * 编辑提示词并重新生成
 */
export async function editAndRegenerate(params: EditAndRegenerateParams): Promise<EditAndRegenerateResult> {
  const res = await fetch(`${API_BASE}/api/batch/edit-and-regenerate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_id: params.recordId,
      project_id: params.projectId,
      segment_index: params.segmentIndex,
      crucial: params.crucial,
      action: params.action,
      sound: params.sound,
      negative_constraint: params.negative_constraint,
      crucial_zh: params.crucial_zh || '',
      action_zh: params.action_zh || '',
      sound_zh: params.sound_zh || '',
      negative_constraint_zh: params.negative_constraint_zh || '',
    }),
  })

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}))
    return {
      success: false,
      error: errorData.detail || errorData.message || `HTTP ${res.status}`,
    }
  }

  return res.json()
}

/**
 * 级联重做
 */
export async function cascadeRedo(params: CascadeRedoParams): Promise<CascadeRedoResult> {
  const res = await fetch(`${API_BASE}/api/batch/cascade-redo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      table_id: params.tableId,
      record_id: params.recordId,
      from_segment_index: params.fromSegmentIndex,
      regenerate_storyboard: params.regenerateStoryboard,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '级联重做失败')
  }

  return res.json()
}
