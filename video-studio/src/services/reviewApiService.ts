/**
 * Sprint 2: 双质量门审核 API 服务
 * 对接后端 /api/v2/blueprint-reviews/* 和 /api/v2/segment-reviews/* 端点
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// ========== 类型定义 ==========

/**
 * 蓝图审核状态
 */
export type BlueprintStatus = 'pending' | 'approved' | 'rejected' | 'edited'

/**
 * 片段审核状态
 */
export type SegmentStatus = 'pending' | 'passed' | 'rejected' | 'skipped'

/**
 * QA 推荐
 */
export type QARecommendation = 'pass' | 'reject' | 'manual_review'

/**
 * 分镜段落
 */
export interface StoryboardSegment {
  segment_index: number
  crucial?: string
  action?: string
  sound?: string
  scene?: string
  prompt?: string
  content?: string
  duration?: number
}

/**
 * 蓝图审核记录
 */
export interface BlueprintReview {
  id: string
  batch_id: string
  run_id?: string
  full_storyboard: {
    segments: StoryboardSegment[]
    [key: string]: unknown
  }
  original_storyboard?: string
  status: BlueprintStatus
  action?: 'approve' | 'edit_approve' | 'reject'
  reviewer_id?: string
  reviewed_at?: string
  reject_count: number
  reject_reason?: string
  created_at: string
}

/**
 * 蓝图列表响应
 */
export interface BlueprintListResponse {
  items: BlueprintReview[]
  total: number
  pending_count: number
}

/**
 * 片段审核记录
 */
export interface SegmentReview {
  id: string
  batch_id: string
  run_id?: string
  segment_index: number
  video_url?: string
  first_frame_url?: string
  last_frame_url?: string
  storyboard_segment?: StoryboardSegment
  qa_confidence?: number
  qa_recommendation?: QARecommendation
  qa_details?: string
  status: SegmentStatus
  action?: 'pass' | 'retry_ai' | 'retry_script'
  reviewer_id?: string
  reviewer_comment?: string
  reviewed_at?: string
  retry_count: number
  created_at: string
}

/**
 * 片段列表响应
 */
export interface SegmentListResponse {
  items: SegmentReview[]
  total: number
  pending_count: number
  auto_passed_count: number
}

/**
 * 操作响应
 */
export interface ActionResponse {
  success: boolean
  message: string
  blueprint_review_id?: string
  segment_review_id?: string
  new_status: string
  next_action?: string
}

// ========== 蓝图审核 API ==========

/**
 * 获取待审核蓝图列表
 */
export async function getPendingBlueprints(
  limit = 50,
  offset = 0
): Promise<BlueprintListResponse> {
  const res = await fetch(
    `${API_BASE}/api/v2/blueprint-reviews/pending?limit=${limit}&offset=${offset}`
  )

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取待审核蓝图列表失败')
  }

  return res.json()
}

/**
 * 获取蓝图详情
 */
export async function getBlueprintDetail(reviewId: string): Promise<BlueprintReview> {
  const res = await fetch(`${API_BASE}/api/v2/blueprint-reviews/${reviewId}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取蓝图详情失败')
  }

  return res.json()
}

/**
 * 批准蓝图
 */
export async function approveBlueprint(
  reviewId: string,
  reviewerId: string,
  comment?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/blueprint-reviews/${reviewId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer_id: reviewerId, comment }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '批准蓝图失败')
  }

  return res.json()
}

/**
 * 编辑并批准蓝图
 */
export async function editAndApproveBlueprint(
  reviewId: string,
  reviewerId: string,
  editedStoryboard: object,
  comment?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/blueprint-reviews/${reviewId}/edit-approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reviewer_id: reviewerId,
      edited_storyboard: editedStoryboard,
      comment,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '编辑并批准蓝图失败')
  }

  return res.json()
}

/**
 * 驳回蓝图
 */
export async function rejectBlueprint(
  reviewId: string,
  reviewerId: string,
  reason: string,
  comment?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/blueprint-reviews/${reviewId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reviewer_id: reviewerId,
      reason,
      comment,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '驳回蓝图失败')
  }

  return res.json()
}

// ========== 片段审核 API ==========

/**
 * 获取待审核片段列表
 */
export async function getPendingSegments(
  batchId?: string,
  limit = 50,
  offset = 0
): Promise<SegmentListResponse> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (batchId) params.append('batch_id', batchId)

  const res = await fetch(`${API_BASE}/api/v2/segment-reviews/pending?${params}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取待审核片段列表失败')
  }

  return res.json()
}

/**
 * 获取批次下所有片段
 */
export async function getBatchSegments(
  batchId: string,
  includeAll = false
): Promise<SegmentListResponse> {
  const res = await fetch(
    `${API_BASE}/api/v2/segment-reviews/batch/${batchId}?include_all=${includeAll}`
  )

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取批次片段失败')
  }

  return res.json()
}

/**
 * 获取片段详情
 */
export async function getSegmentDetail(reviewId: string): Promise<SegmentReview> {
  const res = await fetch(`${API_BASE}/api/v2/segment-reviews/${reviewId}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取片段详情失败')
  }

  return res.json()
}

/**
 * 通过片段审核
 */
export async function passSegment(
  reviewId: string,
  reviewerId: string,
  comment?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/segment-reviews/${reviewId}/pass`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer_id: reviewerId, comment }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '通过片段审核失败')
  }

  return res.json()
}

/**
 * AI 重试（脚本不变）
 */
export async function retrySegmentAI(
  reviewId: string,
  reviewerId: string,
  reason?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/segment-reviews/${reviewId}/retry-ai`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewer_id: reviewerId, reason }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || 'AI 重试失败')
  }

  return res.json()
}

/**
 * 修改脚本后重试
 */
export async function retrySegmentWithScript(
  reviewId: string,
  reviewerId: string,
  editedScript: object,
  reason?: string
): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/api/v2/segment-reviews/${reviewId}/retry-script`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      reviewer_id: reviewerId,
      edited_script: editedScript,
      reason,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '修改脚本重试失败')
  }

  return res.json()
}

// ========== 文件上传 API ==========

/**
 * 上传响应
 */
export interface UploadResponse {
  success: boolean
  file_id: string
  filename: string
  url: string
  storage_path: string
  content_type: string
  size: number
  checksum: string
}

/**
 * 上传文件
 */
export async function uploadFile(
  file: File,
  category = 'general',
  projectId?: string
): Promise<UploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('category', category)
  if (projectId) formData.append('project_id', projectId)

  const res = await fetch(`${API_BASE}/api/v2/storage/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '文件上传失败')
  }

  return res.json()
}

/**
 * 批量上传文件
 */
export async function uploadFiles(
  files: File[],
  category = 'batch',
  projectId?: string
): Promise<UploadResponse[]> {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  formData.append('category', category)
  if (projectId) formData.append('project_id', projectId)

  const res = await fetch(`${API_BASE}/api/v2/storage/upload-batch`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '批量上传失败')
  }

  return res.json()
}
