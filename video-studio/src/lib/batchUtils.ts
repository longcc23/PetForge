/**
 * 批量处理工坊业务逻辑工具库
 * 存放无副作用的纯函数，可单独进行单元测试
 */

import type { BatchTask, BatchStats, Storyboard } from '@/types'

/**
 * 从 storyboardJson 解析分段数组
 * 支持多种格式：
 * 1. { storyboards: [...] }
 * 2. { segments: [...] }
 * 3. 直接数组 [...]
 */
export function parseStoryboardSegments(storyboardJson: string | undefined | null): any[] {
  if (!storyboardJson) {
    return []
  }

  try {
    const parsed = JSON.parse(storyboardJson)
    if (parsed.storyboards && Array.isArray(parsed.storyboards)) {
      return parsed.storyboards
    }
    if (parsed.segments && Array.isArray(parsed.segments)) {
      return parsed.segments
    }
    if (Array.isArray(parsed)) {
      return parsed
    }
    return []
  } catch {
    return []
  }
}

/**
 * 计算任务下一个需要生成的段索引
 * 核心逻辑：优先使用 task.segments（后端已合并 storyboard_json 和 segment_urls 数据）
 *
 * @param task 任务对象
 * @returns 下一个需要生成的段索引，如果没有则返回 null
 */
export function getNextSegmentIndex(task: BatchTask): number | null {
  // 如果没有分镜 JSON，返回 null（需要先生成分镜）
  if (!task.storyboardJson) {
    return null
  }

  // 如果正在生成中或合并中，跳过（避免重复生成）
  if (
    task.status.startsWith('generating_segment_') ||
    task.status === 'merging' ||
    task.status === 'storyboard_generating'
  ) {
    return null
  }

  // 如果已完成，返回 null
  if (task.status === 'completed') {
    return null
  }

  // 优先使用 task.segments（后端已正确合并 storyboard_json 和 segment_urls 的数据）
  // 这是最权威的状态来源
  const useTaskSegments = task.segments && task.segments.length > 0
  const segments = useTaskSegments
    ? task.segments
    : parseStoryboardSegments(task.storyboardJson).map(seg => ({
        status: seg.status || 'pending',
        videoUrl: seg.videoUrl || seg.video_url,
        lastFrameUrl: seg.lastFrameUrl || seg.last_frame_url,
      }))
  
  // 调试日志（1月29日项目）
  if (task.projectId?.includes('cfa572') || task.projectId?.includes('0a505')) {
    console.log(`[getNextSegmentIndex] ${task.projectId}: useTaskSegments=${useTaskSegments}, seg0.status=${segments[0]?.status}, seg1.status=${segments[1]?.status}`)
  }

  if (segments.length === 0) {
    return null
  }

  // 找到第一个未完成的段
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const segmentStatus = seg.status || 'pending'

    if (segmentStatus !== 'completed') {
      // 检查依赖
      if (i === 0) {
        // 段0：只需要首帧图片
        if (task.openingImageUrl) {
          return 0
        }
        return null
      } else {
        // 段N：需要上一段完成
        const prevSeg = segments[i - 1]
        const prevStatus = prevSeg?.status || 'pending'
        if (prevStatus === 'completed') {
          return i
        }
        return null
      }
    }
  }

  // 所有段都完成了
  return null
}

/**
 * 计算批量任务统计数据
 */
export function calculateStats(tasks: BatchTask[]): BatchStats {
  return {
    total: tasks.length,
    completed: tasks.filter(t => t.status === 'completed').length,
    inProgress: tasks.filter(
      t =>
        t.status.includes('generating') ||
        t.status === 'storyboard_generating' ||
        t.status === 'merging'
    ).length,
    failed: tasks.filter(t => t.status === 'failed' || t.status === 'image_failed').length,
  }
}

/**
 * 待生成段信息类型
 */
export interface PendingSegmentInfo {
  taskId: string
  taskIndex: number
  projectId: string
  segmentIndex: number
  segment: (Storyboard & {
    crucial_zh?: string
    action_zh?: string
    sound_zh?: string
    negative_constraint_zh?: string
  }) | null
  inputFrameUrl?: string
  inputFrameLabel?: string
}

/**
 * 计算待生成的段列表
 * @param tasks 所有任务
 * @param selectedRecordIds 选中的记录 ID，为空则处理全部
 */
export function calculatePendingSegments(
  tasks: BatchTask[],
  selectedRecordIds: string[]
): PendingSegmentInfo[] {
  // 筛选要处理的任务
  const tasksToProcess =
    selectedRecordIds.length > 0
      ? tasks.filter(t => selectedRecordIds.includes(t.id))
      : tasks

  const segments: PendingSegmentInfo[] = []

  tasksToProcess.forEach((task, idx) => {
    const nextSeg = getNextSegmentIndex(task)
    if (nextSeg === null) return

    const storyboards = parseStoryboardSegments(task.storyboardJson)
    if (nextSeg >= storyboards.length) return

    const segmentData = storyboards[nextSeg]

    // 确定输入帧
    let inputFrameUrl: string | undefined
    let inputFrameLabel: string | undefined
    if (nextSeg === 0) {
      inputFrameUrl = task.openingImageUrl
      inputFrameLabel = 'Opening Image'
    } else {
      // 上一段的 lastFrameUrl - 优先从 task.segments 获取（后端已正确合并数据）
      const prevSegFromTask = task.segments?.[nextSeg - 1]
      const prevSegFromStoryboard = storyboards[nextSeg - 1]
      inputFrameUrl = prevSegFromTask?.lastFrameUrl || prevSegFromStoryboard?.lastFrameUrl || prevSegFromStoryboard?.last_frame_url
      inputFrameLabel = `段${nextSeg - 1} Last Frame`
    }

    segments.push({
      taskId: task.id,
      taskIndex: idx,
      projectId: task.projectId || '',
      segmentIndex: nextSeg,
      segment: segmentData
        ? {
            id: segmentData.id || `segment-${nextSeg}`,
            segmentIndex: nextSeg,
            segmentType: segmentData.segment_type || segmentData.segmentType || 'eating',
            crucial: segmentData.crucial || '',
            action: segmentData.action || '',
            sound: segmentData.sound || '',
            negative_constraint: segmentData.negative_constraint || '',
            prompt: segmentData.prompt || '',
            status: segmentData.status || 'pending',
            crucial_zh: segmentData.crucial_zh || '',
            action_zh: segmentData.action_zh || '',
            sound_zh: segmentData.sound_zh || '',
            negative_constraint_zh: segmentData.negative_constraint_zh || '',
          }
        : null,
      inputFrameUrl,
      inputFrameLabel,
    })
  })

  return segments
}

/**
 * 按段索引分组任务
 */
export function groupTasksBySegmentIndex(
  tasks: BatchTask[],
  selectedRecordIds: string[]
): Record<number, string[]> {
  const tasksToProcess =
    selectedRecordIds.length > 0
      ? tasks.filter(t => selectedRecordIds.includes(t.id))
      : tasks

  const segmentGroups: Record<number, string[]> = {}

  // 调试：打印所有任务的关键信息
  console.log('[groupTasksBySegmentIndex] 处理任务数:', tasksToProcess.length)
  
  tasksToProcess.forEach(task => {
    const nextSeg = getNextSegmentIndex(task)
    
    // 调试：打印1月29日项目的计算结果
    if (task.projectId?.includes('cfa572') || task.projectId?.includes('0a505') || task.projectId?.includes('07a0ea')) {
      console.log(`[groupTasksBySegmentIndex] ${task.projectId?.slice(0, 8)}: nextSeg=${nextSeg}, task.segments[0].status=${task.segments?.[0]?.status}`)
    }
    
    if (nextSeg !== null) {
      if (!segmentGroups[nextSeg]) {
        segmentGroups[nextSeg] = []
      }
      segmentGroups[nextSeg].push(task.id)
    }
  })

  console.log('[groupTasksBySegmentIndex] 结果:', segmentGroups)
  return segmentGroups
}

/**
 * 生成段汇总文本
 * 例如："段0×3 + 段1×2"
 */
export function formatSegmentSummary(segmentGroups: Record<number, string[]>): string {
  return Object.keys(segmentGroups)
    .map(Number)
    .sort((a, b) => a - b)
    .map(i => `段${i}×${segmentGroups[i].length}`)
    .join(' + ')
}

/**
 * 筛选可生成分镜的任务
 */
export function filterTasksForStoryboard(tasks: BatchTask[]): BatchTask[] {
  return tasks.filter(
    t => t.openingImageUrl && (t.status === 'pending' || t.status === 'storyboard_ready')
  )
}

/**
 * 筛选可合并的任务
 */
export function filterTasksForMerge(tasks: BatchTask[]): BatchTask[] {
  return tasks.filter(t => t.status === 'all_segments_ready')
}

/**
 * 筛选有项目的任务（可同步到云空间）
 */
export function filterTasksWithProject(tasks: BatchTask[]): BatchTask[] {
  return tasks.filter(t => t.projectId)
}
