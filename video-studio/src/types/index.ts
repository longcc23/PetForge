// 演员（宠物）类型
export interface Actor {
  id: string
  name: string
  imageUrl: string
  createdAt: number
}

// 模板类型
export interface Template {
  id: string
  name: string
  description: string
  coverImage: string
  available: boolean
}

// 分镜类型
export interface Storyboard {
  id: string
  segmentIndex: number // 0-6
  segmentType: 'intro' | 'eating' | 'outro'
  crucial: string      // 关键帧描述
  action: string       // 动作描述
  sound: string        // 音效描述
  negative_constraint?: string  // 负向约束
  prompt: string       // 完整提示词
  videoUrl?: string    // 生成的视频URL
  firstFrameUrl?: string  // 首帧URL（用于预览）
  lastFrameUrl?: string   // 尾帧URL（传递给下一段）
  status: 'pending' | 'generating' | 'completed' | 'waiting_confirmation' | 'failed'
  // 每段时长（秒），用于驱动后端 duration_sec，范围 4-8
  durationSec?: number
}

// 项目类型
export interface Project {
  id: string
  templateId: string
  actorImage: string
  actorName?: string
  sceneDescription: string
  openingImageUrl?: string
  storyboards: Storyboard[]
  finalVideoUrl?: string
  status: 'draft' | 'generating_opening' | 'editing_storyboard' | 'generating_video' | 'completed'
  createdAt: number
  updatedAt: number
}

// 生成状态
export interface GenerationStatus {
  currentSegment: number
  totalSegments: number
  status: 'idle' | 'generating' | 'completed' | 'failed'
  message: string
}

// ========== 批量处理工坊类型 ==========

// 飞书配置
export interface FeishuConfig {
  appId: string
  appSecret: string
  appToken?: string  // 可选，如果 tableId 是完整格式则不需要
  tenantAccessToken?: string  // 可选，用于调试，直接使用提供的 token
  tableId: string
  connected: boolean
  tableName?: string
  recordCount?: number
  driveFolderToken?: string  // 飞书云空间文件夹 token，用于上传文件
}

// 批量任务状态
export type BatchTaskStatus =
  | 'pending'           // 待处理
  | 'storyboard_generating'  // 分镜生成中
  | 'storyboard_ready'  // 分镜已生成
  | 'generating_segment_0'   // 生成段0
  | 'generating_segment_1'   // 生成段1
  | 'generating_segment_2'   // 生成段2
  | 'generating_segment_3'   // 生成段3
  | 'generating_segment_4'   // 生成段4
  | 'generating_segment_5'   // 生成段5
  | 'generating_segment_6'   // 生成段6
  | 'all_segments_ready'     // 所有段完成
  | 'merging'           // 合并中
  | 'completed'         // 已完成
  | 'failed'            // 失败
  | 'image_failed'      // 首帧图片获取失败

// 批量任务分段信息
export interface BatchSegment {
  videoUrl?: string
  lastFrameUrl?: string
  status: 'pending' | 'generating' | 'completed' | 'failed'
}

// 批量任务
export interface BatchTask {
  id: string                    // 飞书记录ID
  actorId?: string              // 演员ID（飞书字段 actor_id）
  projectId?: string            // 项目ID（生成后回写）
  openingImageUrl?: string      // 首帧图片URL
  sceneDescription?: string     // 场景描述
  templateId?: string           // 模板ID
  segmentCount: number          // 段数
  storyboardJson?: string       // 分镜JSON
  segments: BatchSegment[]      // 分段信息
  finalVideoUrl?: string        // 最终视频URL
  status: BatchTaskStatus       // 状态
  errorMessage?: string         // 错误信息
  progress: string              // 进度文本，如 "3/5段已完成"
  updatedAt?: string            // 更新时间
  publishDate?: string          // 发布日期（来自飞书 release_date 字段，格式：YYYYMMDD）
}

// 批量任务统计
export interface BatchStats {
  total: number
  completed: number
  inProgress: number
  failed: number
}

// 批量处理配置（高级设置）
export interface BatchSettings {
  storyboardConcurrency: number  // 分镜并发数，默认10
  videoConcurrency: number       // 视频并发数，默认5
  writebackBatchSize: number     // 回写批次大小，默认500
}
