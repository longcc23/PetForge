import { X, Play, RotateCcw, CheckCircle2, Clock, AlertCircle, Loader2, ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { BatchTask, Storyboard } from '@/types'

// API 基础路径（用于拼接 /storage 这类相对路径资源）
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

interface Props {
  task: BatchTask | null
  onClose: () => void
  onRetry: (taskId: string, action: 'storyboard' | 'segment' | 'merge', segmentIndex?: number) => void
  onCascadeRedo?: (taskId: string, fromSegmentIndex: number, regenerateStoryboard: boolean) => Promise<void>
  // 改为通知父组件打开编辑弹窗，而不是在内部渲染
  onOpenPromptEdit?: (taskId: string, segmentIndex: number) => void
}

// 视频预览弹框
function VideoPreviewDialog({
  videoUrl,
  title,
  onClose
}: {
  videoUrl: string
  title: string
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        className="relative bg-zinc-900 rounded-lg overflow-hidden max-w-3xl w-full mx-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-3 border-b border-zinc-700">
          <span className="text-sm text-zinc-300">{title}</span>
          <button
            onClick={onClose}
            className="p-1 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-2">
          <video
            src={videoUrl}
            controls
            autoPlay
            className="w-full rounded"
            style={{ maxHeight: '70vh' }}
          />
        </div>
      </div>
    </div>
  )
}

// 级联重做确认对话框
function CascadeRedoDialog({
  segmentIndex,
  totalSegments,
  onConfirm,
  onCancel
}: {
  segmentIndex: number
  totalSegments: number
  onConfirm: (regenerateStoryboard: boolean) => void
  onCancel: () => void
}) {
  const [regenerateStoryboard, setRegenerateStoryboard] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleConfirm = async () => {
    setLoading(true)
    await onConfirm(regenerateStoryboard)
    setLoading(false)
  }

  const affectedSegments = Array.from(
    { length: totalSegments - segmentIndex },
    (_, i) => segmentIndex + i
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onCancel}
    >
      <div
        className="relative bg-zinc-900 rounded-lg overflow-hidden max-w-md w-full mx-4 p-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-zinc-200">级联重做确认</h3>
          <button
            onClick={onCancel}
            className="p-1 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
            <p className="text-xs text-amber-300">
              将清空从<span className="font-bold text-amber-200">段{segmentIndex}</span>开始的所有视频，
              受影响的分段：{affectedSegments.map(i => `段${i}`).join('、')}
            </p>
            <p className="text-xs text-amber-400 mt-2">
              旧视频会备份到 history 目录，清空后需要手动重新生成。
            </p>
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={regenerateStoryboard}
              onChange={(e) => setRegenerateStoryboard(e.target.checked)}
              className="w-4 h-4 rounded border-zinc-600 bg-zinc-800 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-xs text-zinc-300">同时重新生成分镜（清空受影响段的分镜脚本）</span>
          </label>

          <div className="flex gap-2 pt-2">
            <button
              onClick={onCancel}
              disabled={loading}
              className="flex-1 py-2 bg-zinc-700 hover:bg-zinc-600 disabled:bg-zinc-800 text-white text-sm font-medium rounded-lg"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="flex-1 py-2 bg-red-600 hover:bg-red-500 disabled:bg-red-800 text-white text-sm font-medium rounded-lg flex items-center justify-center gap-2"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
              {loading ? '处理中...' : '确认重做'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function TaskDetail({ task, onClose, onRetry, onCascadeRedo, onOpenPromptEdit }: Props) {
  const [expandedStoryboard, setExpandedStoryboard] = useState(false)
  const [previewVideo, setPreviewVideo] = useState<{ url: string; title: string } | null>(null)
  const [cascadeRedoTarget, setCascadeRedoTarget] = useState<number | null>(null)

  if (!task) {
    return (
      <div className="h-full flex items-center justify-center text-zinc-500 text-sm">
        选择一个任务查看详情
      </div>
    )
  }

  // 解析分镜 JSON
  let storyboards: Storyboard[] = []
  if (task.storyboardJson) {
    try {
      const parsed = JSON.parse(task.storyboardJson)
      // 支持两种格式：直接数组 或 { storyboards: [...] }
      if (Array.isArray(parsed)) {
        storyboards = parsed
      } else if (parsed && Array.isArray(parsed.storyboards)) {
        storyboards = parsed.storyboards
      }
    } catch {
      // 忽略解析错误
    }
  }

  const resolveMediaUrl = (url?: string, bustCache?: boolean) => {
    if (!url) return undefined
    let resolved = url
    if (url.startsWith('/')) {
      resolved = `${API_BASE}${url}`
    }
    // 对视频 URL 添加时间戳参数防止缓存
    if (bustCache && resolved.includes('.mp4')) {
      const separator = resolved.includes('?') ? '&' : '?'
      resolved = `${resolved}${separator}_t=${Date.now()}`
    }
    return resolved
  }

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
        <h3 className="text-sm font-medium text-zinc-200">任务详情</h3>
        <button
          onClick={onClose}
          className="p-1 text-zinc-500 hover:text-white hover:bg-zinc-700 rounded"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* 内容 */}
      <div className="flex-1 overflow-auto py-4 space-y-4">
        {/* 基本信息 */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-zinc-500">任务 ID</span>
            <span className="text-zinc-300 font-mono">{task.id}</span>
          </div>
          {task.projectId && (
            <div className="flex justify-between text-xs">
              <span className="text-zinc-500">项目 ID</span>
              <span className="text-zinc-300 font-mono">{task.projectId}</span>
            </div>
          )}
          <div className="flex justify-between text-xs">
            <span className="text-zinc-500">段数</span>
            <span className="text-zinc-300">{task.segmentCount}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-zinc-500">进度</span>
            <span className="text-zinc-300">{task.progress || '-'}</span>
          </div>
          {task.updatedAt && (
            <div className="flex justify-between text-xs">
              <span className="text-zinc-500">更新时间</span>
              <span className="text-zinc-300">{new Date(task.updatedAt).toLocaleString()}</span>
            </div>
          )}
        </div>

        {/* 首帧预览 */}
        {task.openingImageUrl && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-zinc-400">首帧图片</h4>
            <img
              src={resolveMediaUrl(task.openingImageUrl)}
              alt="首帧"
              className="w-full rounded-lg"
            />
          </div>
        )}

        {/* 场景描述 */}
        {task.sceneDescription && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-zinc-400">场景描述</h4>
            <p className="text-xs text-zinc-300 bg-zinc-800/50 p-2 rounded">
              {task.sceneDescription}
            </p>
          </div>
        )}

        {/* 分镜预览 */}
        {storyboards.length > 0 && (
          <div className="space-y-2">
            <button
              onClick={() => setExpandedStoryboard(!expandedStoryboard)}
              className="flex items-center gap-2 text-xs font-medium text-zinc-400 hover:text-zinc-300"
            >
              分镜脚本 ({storyboards.length}段)
              {expandedStoryboard ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>

            {expandedStoryboard && (
              <div className="space-y-2">
                {storyboards.map((sb, i) => (
                  <div key={i} className="p-2 bg-zinc-800/50 rounded text-xs space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-blue-400 font-medium">段{i}</span>
                      <span className="text-zinc-500">{sb.durationSec || 5}秒</span>
                    </div>
                    <p className="text-zinc-400">{sb.action}</p>
                    {sb.prompt && (
                      <p className="text-zinc-500 text-[10px] mt-1 line-clamp-2">{sb.prompt}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 分段视频 */}
        <div className="space-y-2">
          <h4 className="text-xs font-medium text-zinc-400">分段视频</h4>
          <div className="space-y-1">
            {task.segments.map((segment, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-zinc-800/50 rounded">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-zinc-400">段{i}</span>
                  {segment.status === 'completed' && <CheckCircle2 className="w-3 h-3 text-emerald-400" />}
                  {segment.status === 'generating' && <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />}
                  {segment.status === 'failed' && <AlertCircle className="w-3 h-3 text-red-400" />}
                  {segment.status === 'pending' && <Clock className="w-3 h-3 text-zinc-500" />}
                </div>
                <div className="flex items-center gap-1">
                  {segment.videoUrl && (
                    <button
                      onClick={() => setPreviewVideo({ url: resolveMediaUrl(segment.videoUrl, true)!, title: `段${i} 视频预览` })}
                      className="p-1 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded"
                      title="播放"
                    >
                      <Play className="w-3 h-3" />
                    </button>
                  )}
                  {/* 已完成或失败的段都可以重新生成 */}
                  {(segment.status === 'completed' || segment.status === 'failed') && (
                    <button
                      onClick={() => {
                        // 如果有编辑回调且有分镜数据，通知父组件打开编辑弹窗
                        if (onOpenPromptEdit && storyboards[i]) {
                          onOpenPromptEdit(task.id, i)
                        } else {
                          // 否则直接重试
                          onRetry(task.id, 'segment', i)
                        }
                      }}
                      className="p-1 text-zinc-400 hover:text-orange-400 hover:bg-zinc-700 rounded"
                      title={segment.status === 'completed' ? '重新生成' : '重试'}
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  )}
                  {/* 级联重做按钮：只对已完成的段显示 */}
                  {segment.status === 'completed' && onCascadeRedo && (
                    <button
                      onClick={() => setCascadeRedoTarget(i)}
                      className="p-1 text-zinc-400 hover:text-red-400 hover:bg-zinc-700 rounded"
                      title={`从段${i}开始级联重做`}
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 最终视频 */}
        {task.finalVideoUrl && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-zinc-400">最终视频</h4>
            <video
              src={resolveMediaUrl(task.finalVideoUrl, true)}
              controls
              className="w-full rounded-lg"
            />
          </div>
        )}

        {/* 错误信息 - 只在任务失败时显示 */}
        {task.errorMessage && (task.status === 'failed' || task.status === 'image_failed') && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <h4 className="text-xs font-medium text-red-400 mb-1">错误信息</h4>
            <p className="text-xs text-red-300">{task.errorMessage}</p>
          </div>
        )}
      </div>

      {/* 底部操作 */}
      {(task.status === 'failed' || task.status === 'image_failed') && (
        <div className="pt-3 border-t border-zinc-800">
          <button
            onClick={() => onRetry(task.id, 'storyboard')}
            className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg flex items-center justify-center gap-2"
          >
            <RotateCcw className="w-4 h-4" />
            重新处理
          </button>
        </div>
      )}

      {/* 视频预览弹框 */}
      {previewVideo && (
        <VideoPreviewDialog
          videoUrl={previewVideo.url}
          title={previewVideo.title}
          onClose={() => setPreviewVideo(null)}
        />
      )}

      {/* 级联重做确认对话框 */}
      {cascadeRedoTarget !== null && onCascadeRedo && (
        <CascadeRedoDialog
          segmentIndex={cascadeRedoTarget}
          totalSegments={task.segmentCount}
          onConfirm={async (regenerateStoryboard) => {
            await onCascadeRedo(task.id, cascadeRedoTarget, regenerateStoryboard)
            setCascadeRedoTarget(null)
          }}
          onCancel={() => setCascadeRedoTarget(null)}
        />
      )}

    </div>
  )
}
