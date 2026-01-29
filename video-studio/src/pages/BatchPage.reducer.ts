/**
 * BatchPage 状态管理 Reducer
 * 统一管理页面所有异步状态和关联数据
 */

import type { PageState, PageAction } from './BatchPage.types'

export function pageReducer(state: PageState, action: PageAction): PageState {
  switch (action.type) {
    // ========== 连接相关 ==========
    case 'CONNECT_START':
      return {
        ...state,
        status: 'connecting',
        errorMessage: null,
      }

    case 'CONNECT_SUCCESS':
      return {
        ...state,
        status: 'idle',
        feishuConfig: {
          ...state.feishuConfig,
          connected: true,
          tableName: action.payload.tableName,
          recordCount: action.payload.recordCount,
          driveFolderToken: action.payload.driveFolderToken || state.feishuConfig.driveFolderToken,
        },
      }

    case 'CONNECT_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    case 'DISCONNECT':
      return {
        ...state,
        feishuConfig: {
          ...state.feishuConfig,
          connected: false,
        },
      }

    // ========== 任务加载 ==========
    case 'LOAD_TASKS_START':
      return {
        ...state,
        status: 'loadingTasks',
        errorMessage: null,
      }

    case 'LOAD_TASKS_SUCCESS':
      return {
        ...state,
        status: 'idle',
        tasks: action.payload,
      }

    case 'LOAD_TASKS_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== 分镜生成 ==========
    case 'GENERATE_STORYBOARD_START':
      return {
        ...state,
        status: 'generatingStoryboard',
        errorMessage: null,
      }

    case 'GENERATE_STORYBOARD_SUCCESS':
      return {
        ...state,
        status: 'idle',
      }

    case 'GENERATE_STORYBOARD_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== 视频段生成 ==========
    case 'GENERATE_SEGMENT_START':
      return {
        ...state,
        status: 'generatingSegment',
        currentSegmentIndex: action.payload,
        errorMessage: null,
      }

    case 'GENERATE_SEGMENT_SUCCESS':
      return {
        ...state,
        status: 'idle',
      }

    case 'GENERATE_SEGMENT_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== 合并 ==========
    case 'MERGE_START':
      return {
        ...state,
        status: 'merging',
        errorMessage: null,
      }

    case 'MERGE_SUCCESS':
      return {
        ...state,
        status: 'idle',
      }

    case 'MERGE_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== 同步 ==========
    case 'SYNC_START':
      return {
        ...state,
        status: 'syncing',
        errorMessage: null,
      }

    case 'SYNC_SUCCESS':
      return {
        ...state,
        status: 'idle',
      }

    case 'SYNC_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== 上传到云空间 ==========
    case 'UPLOAD_TO_DRIVE_START':
      return {
        ...state,
        status: 'uploadingToDrive',
        errorMessage: null,
      }

    case 'UPLOAD_TO_DRIVE_SUCCESS':
      return {
        ...state,
        status: 'idle',
      }

    case 'UPLOAD_TO_DRIVE_FAILURE':
      return {
        ...state,
        status: 'error',
        errorMessage: action.payload,
      }

    // ========== UI 状态 ==========
    case 'SELECT_TASK':
      return {
        ...state,
        selectedTaskId: action.payload,
      }

    case 'SET_SELECTED_RECORDS':
      return {
        ...state,
        selectedRecordIds: action.payload,
      }

    case 'SET_STATUS_FILTER':
      return {
        ...state,
        statusFilter: action.payload,
      }

    case 'SET_SHOW_DETAIL':
      return {
        ...state,
        showDetail: action.payload,
      }

    case 'SET_SIDEBAR_COLLAPSED':
      return {
        ...state,
        sidebarCollapsed: action.payload,
      }

    case 'SET_SHOW_BATCH_EDIT_MODAL':
      return {
        ...state,
        showBatchEditModal: action.payload,
      }

    case 'SET_QUEUE_OPEN':
      return {
        ...state,
        queueOpen: action.payload,
      }

    // ========== 配置更新 ==========
    case 'UPDATE_FEISHU_CONFIG':
      return {
        ...state,
        feishuConfig: {
          ...state.feishuConfig,
          ...action.payload,
        },
      }

    case 'UPDATE_SETTINGS':
      return {
        ...state,
        settings: {
          ...state.settings,
          ...action.payload,
        },
      }

    // ========== 错误处理 ==========
    case 'CLEAR_ERROR':
      return {
        ...state,
        status: 'idle',
        errorMessage: null,
      }

    default:
      return state
  }
}
