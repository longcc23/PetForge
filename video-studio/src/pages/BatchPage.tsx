/**
 * 批量处理工坊页面
 *
 * 重构说明：
 * - 状态管理：使用 useReducer 统一管理，替代分散的 useState
 * - API 调用：抽离到 services/batchApiService.ts
 * - 业务逻辑：抽离到 lib/batchUtils.ts
 */

import { useEffect, useCallback, useMemo, useReducer, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft,
  RefreshCw,
  Play,
  Layers,
  Merge,
  Upload,
  FolderOpen,
  ChevronLeft,
  ChevronRight,
  ListChecks,
} from 'lucide-react'
import {
  FeishuConfig,
  TaskTable,
  TaskDetail,
  StatsBar,
  BatchPromptEditModal,
  ApiJobQueueDrawer,
} from '@/components/batch'
import { PromptEditModal } from '@/components/batch/PromptEditModal'
import { useToast } from '@/components/ui/toast'

// 状态管理
import { pageReducer } from './BatchPage.reducer'
import { INITIAL_STATE, DEFAULT_FEISHU_CONFIG, DEFAULT_SETTINGS } from './BatchPage.types'
import type { PageState } from './BatchPage.types'

// API 服务层
import * as batchApi from '@/services/batchApiService'

// 业务逻辑工具
import {
  calculateStats,
  calculatePendingSegments,
  groupTasksBySegmentIndex,
  formatSegmentSummary,
  filterTasksForStoryboard,
  filterTasksForMerge,
  filterTasksWithProject,
} from '@/lib/batchUtils'

// 常量
const SIDEBAR_COLLAPSED_KEY = 'batch_sidebar_collapsed'

/**
 * 从 localStorage 加载初始状态
 */
function loadInitialState(): PageState {
  const savedFeishuConfig = localStorage.getItem('feishu_config')
  const savedSettings = localStorage.getItem('batch_settings')
  const savedSidebarCollapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY)

  return {
    ...INITIAL_STATE,
    feishuConfig: savedFeishuConfig
      ? { ...DEFAULT_FEISHU_CONFIG, ...JSON.parse(savedFeishuConfig) }
      : DEFAULT_FEISHU_CONFIG,
    settings: savedSettings ? JSON.parse(savedSettings) : DEFAULT_SETTINGS,
    sidebarCollapsed: savedSidebarCollapsed === '1',
  }
}

export function BatchPage() {
  const { addToast } = useToast()
  const lastTaskStatusRef = useRef<Map<string, { status: string; errorMessage?: string }>>(
    new Map()
  )

  // 使用 useReducer 统一管理状态
  const [state, dispatch] = useReducer(pageReducer, null, loadInitialState)

  const {
    status,
    feishuConfig,
    tasks,
    selectedTaskId,
    selectedRecordIds,
    statusFilter,
    showDetail,
    sidebarCollapsed,
    showBatchEditModal,
    queueOpen,
    currentSegmentIndex,
    settings,
  } = state

  // 计算派生状态
  const stats = useMemo(() => calculateStats(tasks), [tasks])
  const selectedTask = useMemo(
    () => tasks.find(t => t.id === selectedTaskId) || null,
    [tasks, selectedTaskId]
  )
  const pendingSegments = useMemo(
    () => calculatePendingSegments(tasks, selectedRecordIds),
    [tasks, selectedRecordIds]
  )

  // 单个编辑弹窗状态（从 TaskDetail 提升到顶层）
  const [promptEditState, setPromptEditState] = useState<{
    isOpen: boolean
    taskId: string
    segmentIndex: number
  } | null>(null)

  // 判断是否正在进行异步操作
  const isOperating = status !== 'idle' && status !== 'error'

  // ========== localStorage 持久化 ==========

  useEffect(() => {
    localStorage.setItem('feishu_config', JSON.stringify(feishuConfig))
  }, [feishuConfig])

  useEffect(() => {
    localStorage.setItem('batch_settings', JSON.stringify(settings))
  }, [settings])

  useEffect(() => {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  // ========== API 操作 ==========

  /**
   * 加载任务列表（从本地数据库，快速）
   * 
   * 日常刷新使用此函数，响应时间 < 100ms
   */
  const loadTasks = useCallback(async () => {
    if (!feishuConfig.connected) return

    dispatch({ type: 'LOAD_TASKS_START' })
    try {
      // 使用本地接口，从数据库读取（快速）
      const data = await batchApi.loadTasks(feishuConfig.tableId)
      const nextTasks = data.tasks || []

      // 失败/完成提示
      const nextMap = new Map<string, { status: string; errorMessage?: string }>()
      for (const t of nextTasks) {
        nextMap.set(t.id, { status: t.status, errorMessage: t.errorMessage })
        const prev = lastTaskStatusRef.current.get(t.id)
        if (!prev) continue

        if (prev.status !== 'failed' && t.status === 'failed') {
          addToast(`任务 ${t.id.slice(-6)} 失败：${t.errorMessage || '未知错误'}`, 'error')
        }
        if (prev.status !== 'completed' && t.status === 'completed') {
          addToast(`任务 ${t.id.slice(-6)} 已完成`, 'success')
        }
      }
      lastTaskStatusRef.current = nextMap

      dispatch({ type: 'LOAD_TASKS_SUCCESS', payload: nextTasks })
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '加载失败'

      // 如果后端返回"未连接"，清除前端连接状态
      if (errorMsg.includes('未连接') || errorMsg.includes('未连接飞书表格')) {
        dispatch({ type: 'DISCONNECT' })
        addToast('连接已断开，请重新连接飞书表格', 'error')
        return
      }

      dispatch({ type: 'LOAD_TASKS_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }, [feishuConfig.connected, feishuConfig.tableId, addToast])

  /**
   * 连接飞书
   */
  const handleConnect = async () => {
    dispatch({ type: 'CONNECT_START' })
    try {
      const data = await batchApi.connectFeishu({
        appId: feishuConfig.appId,
        appSecret: feishuConfig.appSecret,
        tableId: feishuConfig.tableId,
        appToken: feishuConfig.appToken,
        tenantAccessToken: feishuConfig.tenantAccessToken,
        driveFolderToken: feishuConfig.driveFolderToken,
      })

      dispatch({
        type: 'CONNECT_SUCCESS',
        payload: {
          tableName: data.table_name || '未知表格',
          recordCount: data.record_count || 0,
          driveFolderToken: data.drive_folder_token,
        },
      })

      addToast('飞书连接成功', 'success')

      // 连接成功后加载任务列表
      // 注意：这里不再使用 setTimeout，而是等待连接完成后再调用
      // loadTasks 会在下一个 effect 中被调用，因为 feishuConfig.connected 变为 true
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '连接失败'
      dispatch({ type: 'CONNECT_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 全量同步任务列表（从飞书，较慢）
   * 
   * 仅在首次连接或需要同步飞书新增记录时使用
   */
  const syncTasksFromFeishu = useCallback(async () => {
    if (!feishuConfig.connected) return

    dispatch({ type: 'LOAD_TASKS_START' })
    try {
      // 使用全量同步接口，从飞书读取
      const data = await batchApi.syncTasksFromFeishu(feishuConfig.tableId)
      const nextTasks = data.tasks || []

      // 更新状态追踪
      const nextMap = new Map<string, { status: string; errorMessage?: string }>()
      for (const t of nextTasks) {
        nextMap.set(t.id, { status: t.status, errorMessage: t.errorMessage })
      }
      lastTaskStatusRef.current = nextMap

      dispatch({ type: 'LOAD_TASKS_SUCCESS', payload: nextTasks })
      addToast(`已同步 ${nextTasks.length} 条任务`, 'success')
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '同步失败'
      dispatch({ type: 'LOAD_TASKS_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }, [feishuConfig.connected, feishuConfig.tableId, addToast])

  /**
   * 连接成功后自动加载任务
   * 
   * 首次连接：使用全量同步（从飞书）
   * 后续刷新：使用本地接口（从数据库）
   */
  useEffect(() => {
    if (feishuConfig.connected && tasks.length === 0 && status === 'idle') {
      // 首次加载使用全量同步
      syncTasksFromFeishu()
    }
  }, [feishuConfig.connected, tasks.length, status, syncTasksFromFeishu])

  /**
   * 从后端恢复配置（页面加载时执行一次）
   */
  useEffect(() => {
    const restoreConfigFromBackend = async () => {
      // 如果 localStorage 已经有完整配置，尝试重建连接
      const savedLocal = localStorage.getItem('feishu_config')
      let configToRestore = null

      if (savedLocal) {
        try {
          const localConfig = JSON.parse(savedLocal)
          if (
            localConfig.appId &&
            localConfig.appSecret &&
            localConfig.tableId &&
            localConfig.connected
          ) {
            console.log('本地已有完整配置，使用本地配置重建后端连接')
            configToRestore = localConfig
          }
        } catch (e) {
          console.error('解析本地配置失败:', e)
        }
      }

      // 如果本地没有完整配置，从后端获取
      if (!configToRestore) {
        try {
          const data = await batchApi.getSavedConnections()
          if (data.connections && data.connections.length > 0) {
            const conn = data.connections[0]
            const detail = await batchApi.getConnectionDetail(conn.table_id)
            configToRestore = {
              appId: detail.app_id,
              appSecret: detail.app_secret,
              appToken: detail.app_token,
              tableId: detail.table_id,
              driveFolderToken: detail.drive_folder_token,
            }
            console.log('已从后端读取飞书配置')
          }
        } catch (e) {
          console.error('从后端读取配置失败:', e)
        }
      }

      // 如果有配置需要恢复，自动重建后端连接
      if (configToRestore) {
        console.log('开始重建后端连接...')
        try {
          const connectData = await batchApi.connectFeishu({
            appId: configToRestore.appId,
            appSecret: configToRestore.appSecret,
            tableId: configToRestore.tableId,
            appToken: configToRestore.appToken,
            driveFolderToken: configToRestore.driveFolderToken,
          })

          dispatch({
            type: 'UPDATE_FEISHU_CONFIG',
            payload: {
              ...configToRestore,
              connected: true,
              tableName: connectData.table_name || '已恢复的连接',
              recordCount: connectData.record_count || 0,
              driveFolderToken: connectData.drive_folder_token || configToRestore.driveFolderToken,
            },
          })

          addToast('已恢复飞书连接配置', 'success')
        } catch (e) {
          console.error('重建连接异常:', e)
          addToast('恢复连接失败，请手动连接', 'error')
        }
      }
    }

    restoreConfigFromBackend()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // 只在组件挂载时执行一次

  /**
   * 批量生成分镜
   */
  const handleGenerateStoryboards = async () => {
    const tasksToProcess =
      selectedRecordIds.length > 0 ? tasks.filter(t => selectedRecordIds.includes(t.id)) : tasks

    if (tasksToProcess.length === 0) {
      addToast(selectedRecordIds.length === 0 ? '请先选择要生成分镜的记录' : '选中的记录为空', 'info')
      return
    }

    const pendingTasks = filterTasksForStoryboard(tasksToProcess)
    if (pendingTasks.length === 0) {
      addToast('没有可生成分镜的任务（需要首帧图片且状态为待处理或分镜已生成）', 'info')
      return
    }

    dispatch({ type: 'GENERATE_STORYBOARD_START' })
    try {
      const data = await batchApi.generateStoryboards({
        tableId: feishuConfig.tableId,
        recordIds: pendingTasks.map(t => t.id),
        concurrency: settings.storyboardConcurrency,
      })

      dispatch({
        type: 'GENERATE_STORYBOARD_SUCCESS',
        payload: { successCount: data.success_count, failedCount: data.failed_count },
      })
      addToast(`分镜生成完成：成功 ${data.success_count}，失败 ${data.failed_count}`, 'success')

      loadTasks()
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '生成失败'
      dispatch({ type: 'GENERATE_STORYBOARD_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 推进下一步：打开批量编辑弹窗
   */
  const handleAdvanceNextStep = () => {
    if (pendingSegments.length === 0) {
      addToast('没有可以推进的任务（请先选择记录、生成分镜或等待上一段完成）', 'info')
      return
    }
    dispatch({ type: 'SET_SHOW_BATCH_EDIT_MODAL', payload: true })
  }

  /**
   * 批量编辑确认后的处理
   */
  const handleBatchEditConfirm = async (
    edits: Array<{
      taskId: string
      projectId: string
      segmentIndex: number
      fields: {
        crucial: string
        action: string
        sound: string
        negative_constraint: string
        crucial_zh?: string
        action_zh?: string
        sound_zh?: string
        negative_constraint_zh?: string
      }
      isModified: boolean
    }>
  ): Promise<{ success: boolean; successCount: number; failedCount: number; error?: string }> => {
    try {
      // 1. 先保存编辑（只保存被修改的）
      const modifiedEdits = edits.filter(e => e.isModified)
      if (modifiedEdits.length > 0) {
        console.log('[批量编辑] 保存修改:', modifiedEdits.length, '个')
        const saveData = await batchApi.batchSavePrompts(
          feishuConfig.tableId,
          modifiedEdits.map(e => ({
            record_id: e.taskId,
            project_id: e.projectId,
            segment_index: e.segmentIndex,
            crucial: e.fields.crucial,
            action: e.fields.action,
            sound: e.fields.sound,
            negative_constraint: e.fields.negative_constraint,
            crucial_zh: e.fields.crucial_zh || '',
            action_zh: e.fields.action_zh || '',
            sound_zh: e.fields.sound_zh || '',
            negative_constraint_zh: e.fields.negative_constraint_zh || '',
            is_modified: true,
          }))
        )
        console.log('[批量编辑] 保存结果:', saveData)
        if (saveData.failed_count > 0) {
          console.warn(
            '[批量编辑] 部分保存失败:',
            saveData.results.filter(r => !r.success)
          )
        }
      }

      // 2. 按段索引分组调用生成 API
      const segmentGroups: Record<number, string[]> = {}
      edits.forEach(e => {
        if (!segmentGroups[e.segmentIndex]) {
          segmentGroups[e.segmentIndex] = []
        }
        segmentGroups[e.segmentIndex].push(e.taskId)
      })

      const segmentIndices = Object.keys(segmentGroups)
        .map(Number)
        .sort((a, b) => a - b)

      let totalSuccess = 0
      let totalFailed = 0

      for (const segmentIndex of segmentIndices) {
        const recordIds = segmentGroups[segmentIndex]
        dispatch({ type: 'GENERATE_SEGMENT_START', payload: segmentIndex })

        console.log(`[批量编辑] 生成段${segmentIndex}:`, recordIds.length, '个任务')
        try {
          const data = await batchApi.generateSegments({
            tableId: feishuConfig.tableId,
            recordIds,
            segmentIndex,
            concurrency: settings.videoConcurrency,
          })
          totalSuccess += data.success_count || 0
          totalFailed += data.failed_count || 0
        } catch {
          totalFailed += recordIds.length
        }
      }

      dispatch({
        type: 'GENERATE_SEGMENT_SUCCESS',
        payload: { successCount: totalSuccess, failedCount: totalFailed },
      })

      // 显示汇总结果
      const summary = segmentIndices.map(i => `段${i}×${segmentGroups[i].length}`).join(' + ')
      if (totalFailed === 0) {
        addToast(`推进完成 (${summary})：成功 ${totalSuccess}`, 'success')
      } else if (totalSuccess === 0) {
        addToast(`推进完成 (${summary})：全部失败 (${totalFailed}个)`, 'error')
      } else {
        addToast(`推进完成 (${summary})：成功 ${totalSuccess}，失败 ${totalFailed}`, 'warning')
      }

      loadTasks()

      return {
        success: totalFailed === 0,
        successCount: totalSuccess,
        failedCount: totalFailed,
      }
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '推进失败'
      addToast(errorMsg, 'error')
      return {
        success: false,
        successCount: 0,
        failedCount: edits.length,
        error: errorMsg,
      }
    }
  }

  /**
   * 同步视频到飞书表格
   */
  const handleSyncVideos = async () => {
    if (!feishuConfig.connected) {
      addToast('请先连接飞书表格', 'info')
      return
    }

    dispatch({ type: 'SYNC_START' })
    try {
      await batchApi.syncVideos(feishuConfig.tableId)
      dispatch({ type: 'SYNC_SUCCESS' })
      addToast('视频已同步到飞书表格', 'success')
      loadTasks()
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '同步失败'
      dispatch({ type: 'SYNC_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 同步到飞书云空间
   */
  const handleSyncToDrive = async () => {
    if (!feishuConfig.connected) {
      addToast('请先连接飞书表格', 'info')
      return
    }

    const tasksWithProject = filterTasksWithProject(tasks)
    if (tasksWithProject.length === 0) {
      addToast('没有可同步的项目', 'info')
      return
    }

    const tasksToSync =
      selectedRecordIds.length > 0
        ? tasksWithProject.filter(t => selectedRecordIds.includes(t.id))
        : tasksWithProject

    if (tasksToSync.length === 0) {
      addToast('选中的任务中没有可同步的项目', 'info')
      return
    }

    const folderToken = feishuConfig.driveFolderToken
    if (!folderToken) {
      addToast('请先在飞书连接配置中填写"云空间文件夹 Token"', 'info')
      return
    }

    dispatch({ type: 'UPLOAD_TO_DRIVE_START' })
    try {
      const projectPublishDates: Record<string, string> = {}
      tasksToSync.forEach(t => {
        if (t.projectId && t.publishDate) {
          projectPublishDates[t.projectId] = t.publishDate
        }
      })

      const projectIds = tasksToSync.map(t => t.projectId).filter(Boolean) as string[]

      const result = await batchApi.syncToDrive({
        tableId: feishuConfig.tableId,
        projectIds,
        projectPublishDates,
        folderToken: folderToken.trim(),
      })

      dispatch({
        type: 'UPLOAD_TO_DRIVE_SUCCESS',
        payload: { success: result.success, total: result.total, failed: result.failed },
      })
      addToast(
        `已同步 ${result.success}/${result.total} 个项目到云空间${result.failed > 0 ? `，${result.failed} 个失败` : ''}`,
        result.failed > 0 ? 'warning' : 'success'
      )
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '同步到云空间失败'
      dispatch({ type: 'UPLOAD_TO_DRIVE_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 批量合并视频
   */
  const handleMergeVideos = async () => {
    const tasksToProcess =
      selectedRecordIds.length > 0 ? tasks.filter(t => selectedRecordIds.includes(t.id)) : tasks

    if (tasksToProcess.length === 0) {
      addToast(selectedRecordIds.length === 0 ? '请先选择要合并的记录' : '选中的记录为空', 'info')
      return
    }

    const readyTasks = filterTasksForMerge(tasksToProcess)
    if (readyTasks.length === 0) {
      addToast('没有可以合并的任务', 'info')
      return
    }

    dispatch({ type: 'MERGE_START' })
    try {
      const data = await batchApi.mergeVideos({
        tableId: feishuConfig.tableId,
        recordIds: readyTasks.map(t => t.id),
      })

      dispatch({
        type: 'MERGE_SUCCESS',
        payload: { successCount: data.success_count, failedCount: data.failed_count },
      })
      addToast(`合并完成：成功 ${data.success_count}，失败 ${data.failed_count}`, 'success')

      loadTasks()
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '合并失败'
      dispatch({ type: 'MERGE_FAILURE', payload: errorMsg })
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 重试单个任务
   */
  const handleRetryTask = async (
    taskId: string,
    action: 'storyboard' | 'segment' | 'merge',
    segmentIndex?: number
  ) => {
    try {
      console.log('开始重试任务:', { taskId, action, segmentIndex, tableId: feishuConfig.tableId })

      await batchApi.retryTask({
        tableId: feishuConfig.tableId,
        recordId: taskId,
        action,
        segmentIndex,
      })

      addToast(`重试成功${action === 'segment' ? ` (段${segmentIndex})` : ''}`, 'success')
      loadTasks()
    } catch (error) {
      console.error('重试任务异常:', error)
      const errorMsg = error instanceof Error ? error.message : '重试失败'
      addToast(errorMsg, 'error')
    }
  }

  /**
   * 上传首帧图片
   */
  const handleUploadImage = async (taskId: string, file: File) => {
    try {
      await batchApi.uploadImage(feishuConfig.tableId, taskId, file)
      addToast('上传成功', 'success')
      loadTasks()
    } catch (error) {
      addToast(error instanceof Error ? error.message : '上传失败', 'error')
    }
  }

  /**
   * 编辑提示词并重新生成
   */
  const handlePromptEdit = async (
    taskId: string,
    segmentIndex: number,
    fields: {
      crucial: string
      action: string
      sound: string
      negative_constraint: string
      crucial_zh?: string
      action_zh?: string
      sound_zh?: string
      negative_constraint_zh?: string
    }
  ): Promise<{
    success: boolean
    submitted?: boolean
    videoUrl?: string
    error?: string
    promptSent?: string
  }> => {
    try {
      const task = tasks.find(t => t.id === taskId)
      const projectId = task?.projectId || ''

      console.log('[编辑提示词] 开始:', { taskId, projectId, segmentIndex, fields })

      if (!projectId) {
        return { success: false, error: '项目 ID 不存在，请先生成分镜' }
      }

      const data = await batchApi.editAndRegenerate({
        tableId: feishuConfig.tableId,
        recordId: taskId,
        projectId,
        segmentIndex,
        crucial: fields.crucial,
        action: fields.action,
        sound: fields.sound,
        negative_constraint: fields.negative_constraint,
        crucial_zh: fields.crucial_zh,
        action_zh: fields.action_zh,
        sound_zh: fields.sound_zh,
        negative_constraint_zh: fields.negative_constraint_zh,
      })

      console.log('[编辑提示词] 成功:', data)

      // 刷新任务列表
      loadTasks()

      if (data.accepted) {
        addToast(`段${segmentIndex} 已提交后台生成（可在列表查看进度）`, 'info')
        return { success: false, submitted: true, promptSent: data.prompt_sent }
      }

      if (data.success) {
        addToast(`段${segmentIndex} 重新生成成功`, 'success')
      } else {
        addToast(data.error || `段${segmentIndex} 生成失败`, 'error')
      }

      return {
        success: data.success,
        videoUrl: data.video_url,
        error: data.error,
        promptSent: data.prompt_sent,
      }
    } catch (error) {
      console.error('[编辑提示词] 异常:', error)
      const errorMsg = error instanceof Error ? error.message : '未知错误'
      return { success: false, error: errorMsg }
    }
  }

  /**
   * 级联重做
   */
  const handleCascadeRedo = async (
    taskId: string,
    fromSegmentIndex: number,
    regenerateStoryboard: boolean
  ) => {
    try {
      console.log(
        '[级联重做] table_id:',
        feishuConfig.tableId,
        'record_id:',
        taskId,
        'from_segment_index:',
        fromSegmentIndex
      )

      const data = await batchApi.cascadeRedo({
        tableId: feishuConfig.tableId,
        recordId: taskId,
        fromSegmentIndex,
        regenerateStoryboard,
      })

      const clearedCount = data.cleared_segments?.length || 0
      const backupCount = data.backup_paths?.length || 0

      addToast(
        `已清空${clearedCount}个分段${backupCount > 0 ? `，${backupCount}个文件已备份` : ''}`,
        'success'
      )

      loadTasks()
    } catch (error) {
      addToast(error instanceof Error ? error.message : '级联重做失败', 'error')
    }
  }

  // ========== UI 事件处理 ==========

  const handleConfigChange = (config: Partial<typeof feishuConfig>) => {
    dispatch({ type: 'UPDATE_FEISHU_CONFIG', payload: config })
  }

  const handleSettingsChange = (newSettings: Partial<typeof settings>) => {
    dispatch({ type: 'UPDATE_SETTINGS', payload: newSettings })
  }

  // 选择变化回调（使用 useCallback 避免无限循环）
  const handleSelectionChange = useCallback((ids: string[]) => {
    dispatch({ type: 'SET_SELECTED_RECORDS', payload: ids })
  }, [])

  // ========== 渲染 ==========

  // 计算底部操作栏数据
  const segmentGroups = useMemo(
    () => groupTasksBySegmentIndex(tasks, selectedRecordIds),
    [tasks, selectedRecordIds]
  )
  const readyCount = Object.values(segmentGroups).reduce((sum, ids) => sum + ids.length, 0)
  const segmentSummary = formatSegmentSummary(segmentGroups)

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* 顶部导航 */}
      <header className="h-14 border-b border-zinc-800 flex items-center justify-between px-4">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-lg font-semibold">批量处理工坊</h1>
            <p className="text-xs text-zinc-500">创作 / AI视频工坊 / 批量处理</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {feishuConfig.connected && (
            <button
              onClick={handleSyncVideos}
              disabled={isOperating}
              className="p-2 text-zinc-400 hover:text-green-400 hover:bg-zinc-800 rounded-lg disabled:opacity-50"
              title="同步到飞书（将生成结果回写到飞书表格）"
            >
              <Upload className={`w-5 h-5 ${status === 'syncing' ? 'animate-pulse text-green-400' : ''}`} />
            </button>
          )}
          {feishuConfig.connected && (
            <button
              onClick={loadTasks}
              disabled={status === 'loadingTasks'}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg disabled:opacity-50"
              title="刷新任务（从数据库读取最新状态）"
            >
              <RefreshCw className={`w-5 h-5 ${status === 'loadingTasks' ? 'animate-spin' : ''}`} />
            </button>
          )}
          {feishuConfig.connected && (
            <button
              onClick={() => dispatch({ type: 'SET_QUEUE_OPEN', payload: true })}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg"
              title="API任务队列"
            >
              <ListChecks className="w-5 h-5" />
            </button>
          )}
        </div>
      </header>

      {/* 主内容区 */}
      <div className="flex h-[calc(100vh-3.5rem)]">
        {/* 左侧配置区 */}
        <aside
          className={`border-r border-zinc-800 overflow-hidden transition-[width] duration-200 ease-out ${
            sidebarCollapsed ? 'w-12' : 'w-80'
          }`}
        >
          <div className={`h-full ${sidebarCollapsed ? 'p-2' : 'p-4'} overflow-auto`}>
            {/* 折叠/展开按钮 */}
            <div
              className={`flex items-center ${sidebarCollapsed ? 'justify-center' : 'justify-between'} mb-3`}
            >
              {!sidebarCollapsed && <span className="text-xs text-zinc-500">配置</span>}
              <button
                onClick={() =>
                  dispatch({ type: 'SET_SIDEBAR_COLLAPSED', payload: !sidebarCollapsed })
                }
                className="p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded"
                title={sidebarCollapsed ? '展开左侧配置区' : '收起左侧配置区'}
              >
                {sidebarCollapsed ? (
                  <ChevronRight className="w-4 h-4" />
                ) : (
                  <ChevronLeft className="w-4 h-4" />
                )}
              </button>
            </div>

            {!sidebarCollapsed ? (
              <FeishuConfig
                config={feishuConfig}
                settings={settings}
                onConfigChange={handleConfigChange}
                onSettingsChange={handleSettingsChange}
                onConnect={handleConnect}
                connecting={status === 'connecting'}
              />
            ) : (
              <div className="flex flex-col items-center gap-3 pt-2">
                <div
                  className={`w-2 h-2 rounded-full ${
                    feishuConfig.connected ? 'bg-emerald-400' : 'bg-zinc-600'
                  }`}
                  title={feishuConfig.connected ? '飞书已连接' : '飞书未连接'}
                />
              </div>
            )}
          </div>
        </aside>

        {/* 中间任务列表区 */}
        <main className="flex-1 flex flex-col p-4 overflow-hidden">
          {/* 统计栏 */}
          {feishuConfig.connected && tasks.length > 0 && (
            <div className="mb-4">
              <StatsBar stats={stats} />
            </div>
          )}

          {/* 任务列表 */}
          <div className="flex-1 overflow-hidden">
            {!feishuConfig.connected ? (
              <div className="h-full flex items-center justify-center text-zinc-500">
                请先在左侧配置飞书连接
              </div>
            ) : status === 'loadingTasks' ? (
              <div className="h-full flex items-center justify-center text-zinc-500">
                <RefreshCw className="w-5 h-5 animate-spin mr-2" />
                加载中...
              </div>
            ) : (
              <TaskTable
                tasks={tasks}
                selectedTaskId={selectedTaskId}
                onSelectTask={id => dispatch({ type: 'SELECT_TASK', payload: id })}
                onUploadImage={handleUploadImage}
                statusFilter={statusFilter}
                onStatusFilterChange={filter =>
                  dispatch({ type: 'SET_STATUS_FILTER', payload: filter })
                }
                onSelectionChange={handleSelectionChange}
              />
            )}
          </div>

          {/* 底部操作栏 */}
          {feishuConfig.connected && tasks.length > 0 && (
            <div className="mt-4 pt-4 border-t border-zinc-800">
              {/* 已选择计数 */}
              <div className="mb-3 text-xs text-zinc-500 flex items-center justify-between">
                <span>
                  已选择:{' '}
                  <span className="text-pink-400 font-medium">{selectedRecordIds.length}</span> /{' '}
                  {tasks.length} 条
                  {selectedRecordIds.length > 0 && readyCount < selectedRecordIds.length && (
                    <span className="ml-2 text-zinc-600">（可推进: {readyCount} 条）</span>
                  )}
                </span>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={handleGenerateStoryboards}
                  disabled={isOperating}
                  className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg flex items-center gap-2 transition-colors"
                >
                  <Layers className="w-4 h-4" />
                  {status === 'generatingStoryboard' ? '生成中...' : '生成分镜'}
                </button>

                <button
                  onClick={handleAdvanceNextStep}
                  disabled={isOperating || readyCount === 0}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg flex items-center gap-2 transition-colors"
                  title={readyCount > 0 ? `本次将生成: ${segmentSummary}` : '没有可推进的任务'}
                >
                  <Play className="w-4 h-4" />
                  {status === 'generatingSegment'
                    ? `生成段${currentSegmentIndex}中...`
                    : `生成视频`}
                  {readyCount > 0 && !isOperating && (
                    <span className="ml-1 px-1.5 py-0.5 bg-blue-500 rounded text-xs">
                      {readyCount}
                    </span>
                  )}
                </button>

                <button
                  onClick={handleMergeVideos}
                  disabled={isOperating}
                  className="px-4 py-2 bg-purple-600 hover:bg-purple-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg flex items-center gap-2 transition-colors"
                >
                  <Merge className="w-4 h-4" />
                  {status === 'merging' ? '合并中...' : '合并视频'}
                </button>

                <button
                  onClick={handleSyncToDrive}
                  disabled={isOperating}
                  className="px-4 py-2 bg-orange-600 hover:bg-orange-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg flex items-center gap-2 transition-colors"
                  title="将项目文件上传到飞书云空间文件夹"
                >
                  <FolderOpen className="w-4 h-4" />
                  {status === 'uploadingToDrive' ? '上传中...' : '同步到云空间'}
                </button>
              </div>

              {/* 推进预览信息 */}
              {readyCount > 0 && !isOperating && (
                <div className="mt-2 text-xs text-zinc-500">
                  {selectedRecordIds.length > 0 ? `选中记录中 - ` : ''}本次将生成: {segmentSummary}
                </div>
              )}
            </div>
          )}
        </main>

        {/* 右侧详情面板 */}
        {showDetail && (
          <aside className="w-96 border-l border-zinc-800 p-4 overflow-auto">
            <TaskDetail
              task={selectedTask}
              onClose={() => dispatch({ type: 'SET_SHOW_DETAIL', payload: false })}
              onRetry={handleRetryTask}
              onCascadeRedo={handleCascadeRedo}
              onOpenPromptEdit={(taskId, segmentIndex) => {
                setPromptEditState({ isOpen: true, taskId, segmentIndex })
              }}
            />
          </aside>
        )}
      </div>

      {/* 批量编辑弹窗 */}
      <BatchPromptEditModal
        isOpen={showBatchEditModal}
        tasks={tasks}
        pendingSegments={pendingSegments}
        onClose={() => dispatch({ type: 'SET_SHOW_BATCH_EDIT_MODAL', payload: false })}
        onConfirm={handleBatchEditConfirm}
      />

      {/* API 任务队列 */}
      <ApiJobQueueDrawer
        isOpen={queueOpen}
        tableId={feishuConfig.tableId}
        onClose={() => dispatch({ type: 'SET_QUEUE_OPEN', payload: false })}
        onSelectTask={rid => {
          dispatch({ type: 'SELECT_TASK', payload: rid })
          dispatch({ type: 'SET_SHOW_DETAIL', payload: true })
        }}
      />

      {/* 单个编辑弹窗 - 从 TaskDetail 提升到顶层，避免被 aside 容器影响 */}
      {promptEditState && (() => {
        const editTask = tasks.find(t => t.id === promptEditState.taskId)
        if (!editTask) return null
        
        // 解析 storyboard
        let storyboards: any[] = []
        if (editTask.storyboardJson) {
          try {
            const parsed = JSON.parse(editTask.storyboardJson)
            storyboards = Array.isArray(parsed) ? parsed : (parsed.storyboards || [])
          } catch { /* ignore */ }
        }
        
        const segment = storyboards[promptEditState.segmentIndex] || null
        
        // 获取输入帧
        const getInputFrame = () => {
          const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
          const idx = promptEditState.segmentIndex
          if (idx === 0) {
            return { 
              url: editTask.openingImageUrl || `${API_BASE}/storage/projects/${editTask.projectId}/opening_image.jpg`,
              label: 'opening image' 
            }
          }
          const prevSeg = storyboards[idx - 1]
          const lastFrame = prevSeg?.lastFrameUrl || prevSeg?.last_frame_url
          return { 
            url: lastFrame || `${API_BASE}/storage/projects/${editTask.projectId}/frames/segment_${idx - 1}_last.jpg`,
            label: `段${idx - 1} last frame` 
          }
        }
        
        const inputFrame = getInputFrame()
        
        return (
          <PromptEditModal
            isOpen={true}
            taskId={promptEditState.taskId}
            projectId={editTask.projectId || ''}
            segment={segment}
            segmentIndex={promptEditState.segmentIndex}
            inputFrameUrl={inputFrame.url}
            inputFrameLabel={inputFrame.label}
            onClose={() => setPromptEditState(null)}
            onSubmit={async (fields) => {
              const result = await handlePromptEdit(promptEditState.taskId, promptEditState.segmentIndex, fields)
              return result
            }}
          />
        )
      })()}
    </div>
  )
}
