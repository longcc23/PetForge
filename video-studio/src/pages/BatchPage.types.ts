/**
 * BatchPage 状态管理类型定义
 */

import type { FeishuConfig, BatchTask, BatchSettings, BatchTaskStatus } from '@/types'

// ========== 页面状态 ==========

/**
 * 页面异步操作状态
 * 互斥状态，同一时间只能处于其中一种
 */
export type PageStatus =
  | 'idle'                    // 空闲
  | 'connecting'              // 连接飞书中
  | 'loadingTasks'            // 加载任务中
  | 'generatingStoryboard'    // 生成分镜中
  | 'generatingSegment'       // 生成视频段中
  | 'merging'                 // 合并视频中
  | 'syncing'                 // 同步中
  | 'uploadingToDrive'        // 上传到云空间中
  | 'error'                   // 错误状态

/**
 * 页面主状态
 */
export interface PageState {
  // 异步状态
  status: PageStatus
  errorMessage: string | null

  // 飞书配置
  feishuConfig: FeishuConfig

  // 任务数据
  tasks: BatchTask[]
  selectedTaskId: string | null
  selectedRecordIds: string[]

  // UI 状态
  statusFilter: BatchTaskStatus | 'all'
  showDetail: boolean
  sidebarCollapsed: boolean
  showBatchEditModal: boolean
  queueOpen: boolean

  // 生成状态
  currentSegmentIndex: number

  // 设置
  settings: BatchSettings
}

// ========== Action 类型 ==========

export type PageAction =
  // 连接相关
  | { type: 'CONNECT_START' }
  | { type: 'CONNECT_SUCCESS'; payload: { tableName: string; recordCount: number; driveFolderToken?: string } }
  | { type: 'CONNECT_FAILURE'; payload: string }
  | { type: 'DISCONNECT' }

  // 任务加载
  | { type: 'LOAD_TASKS_START' }
  | { type: 'LOAD_TASKS_SUCCESS'; payload: BatchTask[] }
  | { type: 'LOAD_TASKS_FAILURE'; payload: string }

  // 分镜生成
  | { type: 'GENERATE_STORYBOARD_START' }
  | { type: 'GENERATE_STORYBOARD_SUCCESS'; payload: { successCount: number; failedCount: number } }
  | { type: 'GENERATE_STORYBOARD_FAILURE'; payload: string }

  // 视频段生成
  | { type: 'GENERATE_SEGMENT_START'; payload: number }  // payload 是 segmentIndex
  | { type: 'GENERATE_SEGMENT_SUCCESS'; payload: { successCount: number; failedCount: number } }
  | { type: 'GENERATE_SEGMENT_FAILURE'; payload: string }

  // 合并
  | { type: 'MERGE_START' }
  | { type: 'MERGE_SUCCESS'; payload: { successCount: number; failedCount: number } }
  | { type: 'MERGE_FAILURE'; payload: string }

  // 同步
  | { type: 'SYNC_START' }
  | { type: 'SYNC_SUCCESS' }
  | { type: 'SYNC_FAILURE'; payload: string }

  // 上传到云空间
  | { type: 'UPLOAD_TO_DRIVE_START' }
  | { type: 'UPLOAD_TO_DRIVE_SUCCESS'; payload: { success: number; total: number; failed: number } }
  | { type: 'UPLOAD_TO_DRIVE_FAILURE'; payload: string }

  // UI 状态
  | { type: 'SELECT_TASK'; payload: string | null }
  | { type: 'SET_SELECTED_RECORDS'; payload: string[] }
  | { type: 'SET_STATUS_FILTER'; payload: BatchTaskStatus | 'all' }
  | { type: 'SET_SHOW_DETAIL'; payload: boolean }
  | { type: 'SET_SIDEBAR_COLLAPSED'; payload: boolean }
  | { type: 'SET_SHOW_BATCH_EDIT_MODAL'; payload: boolean }
  | { type: 'SET_QUEUE_OPEN'; payload: boolean }

  // 配置更新
  | { type: 'UPDATE_FEISHU_CONFIG'; payload: Partial<FeishuConfig> }
  | { type: 'UPDATE_SETTINGS'; payload: Partial<BatchSettings> }

  // 重置错误
  | { type: 'CLEAR_ERROR' }

// ========== 默认值 ==========

export const DEFAULT_SETTINGS: BatchSettings = {
  storyboardConcurrency: 10,
  videoConcurrency: 5,
  writebackBatchSize: 500,
}

export const DEFAULT_FEISHU_CONFIG: FeishuConfig = {
  appId: '',
  appSecret: '',
  appToken: '',
  tableId: '',
  connected: false,
  driveFolderToken: 'LO1jf6cT7lOEuXdHYXScSV8Vnth',
}

export const INITIAL_STATE: PageState = {
  status: 'idle',
  errorMessage: null,
  feishuConfig: DEFAULT_FEISHU_CONFIG,
  tasks: [],
  selectedTaskId: null,
  selectedRecordIds: [],
  statusFilter: 'all',
  showDetail: true,
  sidebarCollapsed: false,
  showBatchEditModal: false,
  queueOpen: false,
  currentSegmentIndex: 0,
  settings: DEFAULT_SETTINGS,
}
