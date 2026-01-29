/**
 * V2 API 服务层
 * 直接对接后端 /api/v2/* 端点
 * 禁止使用 Mock 数据
 */

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// ========== 类型定义 ==========

/**
 * 工作流状态
 */
export type WorkflowStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'

/**
 * 步骤状态
 */
export type StepStatus = 'pending' | 'dispatched' | 'running' | 'completed' | 'failed' | 'skipped' | 'retrying'

/**
 * 模板信息
 */
export interface TemplateInfo {
  template_id: string
  workflow_type: string
  name: string
  description?: string
  total_steps: number
  max_parallel_tasks: number
}

/**
 * 模板详情
 */
export interface TemplateDetail extends TemplateInfo {
  steps: StepDefinition[]
  enable_manual_intervention: boolean
  auto_retry: boolean
}

/**
 * 步骤定义
 */
export interface StepDefinition {
  step_id: string
  step_name: string
  step_type: string
  order: number
  task_name?: string
  task_params: Record<string, unknown>
  depends_on: string[]
  is_parallel: boolean
  max_retries: number
  retry_delay: number
  soft_timeout?: number
  hard_timeout?: number
  condition?: string
  on_failure: string
}

/**
 * 工作流运行请求
 */
export interface WorkflowRunRequest {
  project_id: string
  workflow_type: string
  template_id?: string
  input_params: Record<string, unknown>
  auto_start?: boolean
}

/**
 * 工作流运行响应
 */
export interface WorkflowRunResponse {
  run_id: string
  project_id: string
  status: WorkflowStatus
  total_steps: number
  workflow_type: string
  created_at: string
  started_at?: string
  message?: string
}

/**
 * 工作流状态响应
 */
export interface WorkflowStatusResponse {
  run_id: string
  project_id: string
  status: WorkflowStatus
  total_steps: number
  completed_steps: number
  progress: number
  current_step_id?: string
  created_at?: string
  started_at?: string
  completed_at?: string
  steps: StepInfo[]
}

/**
 * 步骤信息
 */
export interface StepInfo {
  step_id: string
  step_name: string
  status: StepStatus
  order: number
  progress: number
}

/**
 * 任务信息
 */
export interface TaskInfo {
  task_id: string
  state: string
  info?: Record<string, unknown>
  result?: Record<string, unknown>
  workflow_run_id?: string
  step_id?: string
}

/**
 * 活跃任务响应
 */
export interface ActiveTasksResponse {
  count: number
  tasks: Record<string, unknown>[]
}

// ========== API 函数 ==========

/**
 * 获取所有模板
 */
export async function getTemplates(): Promise<{ count: number; templates: TemplateInfo[] }> {
  const res = await fetch(`${API_BASE}/api/v2/templates`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取模板列表失败')
  }

  return res.json()
}

/**
 * 获取模板详情
 */
export async function getTemplate(templateId: string): Promise<TemplateDetail> {
  const res = await fetch(`${API_BASE}/api/v2/templates/${templateId}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取模板详情失败')
  }

  return res.json()
}

/**
 * 投递工作流
 */
export async function runWorkflow(params: WorkflowRunRequest): Promise<WorkflowRunResponse> {
  const res = await fetch(`${API_BASE}/api/v2/workflow/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '投递工作流失败')
  }

  return res.json()
}

/**
 * 查询工作流状态
 */
export async function getWorkflowStatus(runId: string): Promise<WorkflowStatusResponse> {
  const res = await fetch(`${API_BASE}/api/v2/workflow/status/${runId}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '查询工作流状态失败')
  }

  return res.json()
}

/**
 * 启动工作流
 */
export async function startWorkflow(runId: string): Promise<WorkflowRunResponse> {
  const res = await fetch(`${API_BASE}/api/v2/workflow/start/${runId}`, {
    method: 'POST',
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '启动工作流失败')
  }

  return res.json()
}

/**
 * 取消工作流
 */
export async function cancelWorkflow(runId: string): Promise<{ run_id: string; status: string; message: string; cancelled_steps: number }> {
  const res = await fetch(`${API_BASE}/api/v2/workflow/cancel/${runId}`, {
    method: 'POST',
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '取消工作流失败')
  }

  return res.json()
}

/**
 * 查询任务状态
 */
export async function getTaskStatus(taskId: string): Promise<TaskInfo> {
  const res = await fetch(`${API_BASE}/api/v2/tasks/${taskId}`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '查询任务状态失败')
  }

  return res.json()
}

/**
 * 获取工作流的所有步骤
 */
export async function getWorkflowSteps(runId: string): Promise<{
  run_id: string
  count: number
  steps: Array<{
    step_id: string
    step_name: string
    status: StepStatus
    order: number
    celery_task_id?: string
    progress: number
    error_message?: string
    created_at?: string
    started_at?: string
    completed_at?: string
  }>
}> {
  const res = await fetch(`${API_BASE}/api/v2/tasks/workflow/${runId}/steps`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取工作流步骤失败')
  }

  return res.json()
}

/**
 * 获取活跃任务
 */
export async function getActiveTasks(): Promise<ActiveTasksResponse> {
  const res = await fetch(`${API_BASE}/api/v2/tasks/active`)

  if (!res.ok) {
    const error = await res.json().catch(() => ({}))
    throw new Error(error.detail || '获取活跃任务失败')
  }

  return res.json()
}
