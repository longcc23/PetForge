import { useState, useEffect, useMemo, useCallback } from 'react'
import { X, Loader2, ChevronLeft, ChevronRight, Play, CheckCircle2, AlertCircle } from 'lucide-react'
import type { BatchTask, Storyboard } from '@/types'

type ModalStatus = 'editing' | 'saving' | 'generating' | 'completed'

// 扩展 Storyboard 类型以包含中文字段
interface ExtendedStoryboard extends Storyboard {
  crucial_zh?: string
  action_zh?: string
  sound_zh?: string
  negative_constraint_zh?: string
}

// 待生成的段信息
interface PendingSegment {
  taskId: string
  taskIndex: number
  projectId: string
  segmentIndex: number
  segment: ExtendedStoryboard | null
  inputFrameUrl?: string
  inputFrameLabel?: string
}

// 编辑状态 - 只存储英文（中文仅作参考）
interface EditState {
  crucial: string
  action: string
  sound: string
  negative_constraint: string
  // 中文参考（只读）
  crucial_zh: string
  action_zh: string
  sound_zh: string
  negative_constraint_zh: string
  isModified: boolean
}

// 带中文参考的输入框组件 - 中文直接显示在下方
function FieldWithZhHint({
  label,
  value,
  zhHint,
  onChange,
  placeholder,
  rows = 3,
  required = false,
}: {
  label: string
  value: string
  zhHint?: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
  required?: boolean
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-zinc-400 mb-1.5">
        {label} {required && <span className="text-red-400">*</span>}
      </label>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={rows}
        className="w-full px-3 py-2 text-sm bg-zinc-800 border border-zinc-600 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 resize-none leading-relaxed"
        placeholder={placeholder || "输入英文..."}
      />
      {/* 中文参考直接显示在下方 */}
      {zhHint && (
        <div className="mt-1.5 px-2 py-1.5 bg-zinc-800/30 border border-zinc-700/30 rounded text-[11px] text-zinc-500 leading-relaxed">
          <span className="text-zinc-600 mr-1">参考:</span>
          {zhHint}
        </div>
      )}
    </div>
  )
}

interface Props {
  isOpen: boolean
  tasks: BatchTask[]
  pendingSegments: PendingSegment[]
  onClose: () => void
  onConfirm: (edits: Array<{
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
  }>) => Promise<{ success: boolean; successCount: number; failedCount: number; error?: string }>
}

export function BatchPromptEditModal({
  isOpen,
  tasks: _tasks,
  pendingSegments,
  onClose,
  onConfirm
}: Props) {
  const [status, setStatus] = useState<ModalStatus>('editing')
  const [currentIndex, setCurrentIndex] = useState(0)
  const [editStates, setEditStates] = useState<Record<string, EditState>>({})
  const [result, setResult] = useState<{ successCount: number; failedCount: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 初始化编辑状态 - 英文和中文分开存储
  useEffect(() => {
    if (isOpen && pendingSegments.length > 0) {
      const initialStates: Record<string, EditState> = {}
      pendingSegments.forEach(ps => {
        const key = `${ps.taskId}-${ps.segmentIndex}`
        const seg = ps.segment as ExtendedStoryboard | null
        initialStates[key] = {
          // 英文字段（可编辑）
          crucial: seg?.crucial || '',
          action: seg?.action || '',
          sound: seg?.sound || '',
          negative_constraint: seg?.negative_constraint || '',
          // 中文字段（只读参考）
          crucial_zh: seg?.crucial_zh || '',
          action_zh: seg?.action_zh || '',
          sound_zh: seg?.sound_zh || '',
          negative_constraint_zh: seg?.negative_constraint_zh || '',
          isModified: false,
        }
      })
      setEditStates(initialStates)
      setCurrentIndex(0)
      setStatus('editing')
      setResult(null)
      setError(null)
    }
  }, [isOpen, pendingSegments])

  // 当前任务
  const currentSegment = pendingSegments[currentIndex]
  const currentKey = currentSegment ? `${currentSegment.taskId}-${currentSegment.segmentIndex}` : ''
  const currentEditState = editStates[currentKey] || { 
    crucial: '', action: '', sound: '', negative_constraint: '',
    crucial_zh: '', action_zh: '', sound_zh: '', negative_constraint_zh: '',
    isModified: false 
  }

  // 按段索引分组的统计
  const segmentStats = useMemo(() => {
    const stats: Record<number, number> = {}
    pendingSegments.forEach(ps => {
      stats[ps.segmentIndex] = (stats[ps.segmentIndex] || 0) + 1
    })
    return Object.entries(stats)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([index, count]) => `段${index}×${count}`)
      .join(' + ')
  }, [pendingSegments])

  // 修改数量
  const modifiedCount = useMemo(() => {
    return Object.values(editStates).filter(s => s.isModified).length
  }, [editStates])

  // 切换任务
  const goToPrev = useCallback(() => {
    setCurrentIndex(prev => (prev > 0 ? prev - 1 : prev))
  }, [])

  const goToNext = useCallback(() => {
    setCurrentIndex(prev => (prev < pendingSegments.length - 1 ? prev + 1 : prev))
  }, [pendingSegments.length])

  // 键盘导航
  useEffect(() => {
    if (!isOpen || status !== 'editing') return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') {
        e.preventDefault()
        goToPrev()
      } else if (e.key === 'ArrowRight') {
        e.preventDefault()
        goToNext()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, status, goToPrev, goToNext])

  // 处理字段变更
  const handleFieldChange = (field: keyof EditState, value: string) => {
    if (!currentKey) return
    setEditStates(prev => ({
      ...prev,
      [currentKey]: {
        ...prev[currentKey],
        [field]: value,
        isModified: true,
      }
    }))
  }

  // 处理确认
  const handleConfirm = async () => {
    setStatus('saving')
    setError(null)

    try {
      // 构建编辑数据 - 英文和中文已分开存储
      const edits = pendingSegments.map(ps => {
        const key = `${ps.taskId}-${ps.segmentIndex}`
        const state = editStates[key]

        return {
          taskId: ps.taskId,
          projectId: ps.projectId,
          segmentIndex: ps.segmentIndex,
          fields: {
            crucial: state.crucial.trim(),
            action: state.action.trim(),
            sound: state.sound.trim(),
            negative_constraint: state.negative_constraint.trim(),
            crucial_zh: state.crucial_zh.trim(),
            action_zh: state.action_zh.trim(),
            sound_zh: state.sound_zh.trim(),
            negative_constraint_zh: state.negative_constraint_zh.trim(),
          },
          isModified: state.isModified,
        }
      })

      setStatus('generating')
      const res = await onConfirm(edits)

      setResult({
        successCount: res.successCount,
        failedCount: res.failedCount,
      })

      if (res.success) {
        setStatus('completed')
      } else {
        setError(res.error || '部分任务失败')
        setStatus('completed')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误')
      setStatus('completed')
    }
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        className="relative bg-zinc-900 rounded-lg overflow-hidden w-full max-w-5xl mx-4 max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
          <div>
            <h3 className="text-sm font-medium text-zinc-200">
              推进下一步 - 确认并编辑提示词
            </h3>
            <p className="text-xs text-zinc-500 mt-0.5">
              本次将生成: {segmentStats}（共 {pendingSegments.length} 个段）
              {modifiedCount > 0 && (
                <span className="text-blue-400 ml-2">· {modifiedCount} 个已修改</span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-auto p-4">
          {status === 'editing' && currentSegment && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 h-full">
              {/* 左侧：输入帧预览 */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-medium text-zinc-400">用于生成该段的首帧图</h4>
                  {currentSegment.inputFrameLabel && (
                    <span className="text-[10px] text-zinc-500">{currentSegment.inputFrameLabel}</span>
                  )}
                </div>
                <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg overflow-hidden">
                  {currentSegment.inputFrameUrl ? (
                    <img
                      src={currentSegment.inputFrameUrl}
                      alt="输入首帧"
                      className="w-full h-auto object-contain max-h-[300px]"
                    />
                  ) : (
                    <div className="p-6 text-xs text-zinc-500 text-center">
                      未找到该段的输入首帧<br />
                      （段0应为 opening image；段N应为上一段 last frame）
                    </div>
                  )}
                </div>
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300 leading-relaxed">
                  <span className="font-medium">提示：</span>编辑英文 prompt，中文仅供参考。
                </div>
              </div>

              {/* 右侧：字段编辑 - 只编辑英文，中文作为提示 */}
              <div className="space-y-4">
                {/* 关键画面 - 必填 */}
                <FieldWithZhHint
                  label="关键画面 Crucial"
                  value={currentEditState.crucial}
                  zhHint={currentEditState.crucial_zh}
                  onChange={value => handleFieldChange('crucial', value)}
                  placeholder="Describe the key visual elements..."
                  rows={4}
                  required
                />

                {/* 动作描述 - 高度加大 */}
                <FieldWithZhHint
                  label="动作描述 Action"
                  value={currentEditState.action}
                  zhHint={currentEditState.action_zh}
                  onChange={value => handleFieldChange('action', value)}
                  placeholder="Describe the movement and actions..."
                  rows={5}
                />

                {/* 音效描述 - 全宽，只在有内容时显示 */}
                {(currentEditState.sound || currentEditState.sound_zh) && (
                  <FieldWithZhHint
                    label="音效描述 Sound"
                    value={currentEditState.sound}
                    zhHint={currentEditState.sound_zh}
                    onChange={value => handleFieldChange('sound', value)}
                    placeholder="Sound effects..."
                    rows={2}
                  />
                )}

                {/* 负向约束 - 全宽，只在有内容时显示 */}
                {(currentEditState.negative_constraint || currentEditState.negative_constraint_zh) && (
                  <FieldWithZhHint
                    label="负向约束 Negative"
                    value={currentEditState.negative_constraint}
                    zhHint={currentEditState.negative_constraint_zh}
                    onChange={value => handleFieldChange('negative_constraint', value)}
                    placeholder="What to avoid..."
                    rows={2}
                  />
                )}
              </div>
            </div>
          )}

          {(status === 'saving' || status === 'generating') && (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-12 h-12 text-blue-400 animate-spin mb-4" />
              <p className="text-sm text-zinc-300 mb-2">
                {status === 'saving' ? '保存编辑中...' : '批量生成中...'}
              </p>
              <p className="text-xs text-zinc-500">
                {segmentStats}，请稍候...
              </p>
            </div>
          )}

          {status === 'completed' && (
            <div className="flex flex-col items-center justify-center py-16">
              {result && result.failedCount === 0 ? (
                <>
                  <CheckCircle2 className="w-14 h-14 text-emerald-400 mb-4" />
                  <p className="text-base text-zinc-200 mb-2">推进完成！</p>
                  <p className="text-sm text-zinc-400">
                    成功生成 {result.successCount} 个段
                  </p>
                </>
              ) : result && result.successCount > 0 ? (
                <>
                  <AlertCircle className="w-14 h-14 text-yellow-400 mb-4" />
                  <p className="text-base text-zinc-200 mb-2">部分完成</p>
                  <p className="text-sm text-zinc-400">
                    成功 {result.successCount} 个，失败 {result.failedCount} 个
                  </p>
                  {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
                </>
              ) : (
                <>
                  <AlertCircle className="w-14 h-14 text-red-400 mb-4" />
                  <p className="text-base text-zinc-200 mb-2">生成失败</p>
                  <p className="text-sm text-red-400">{error || '未知错误'}</p>
                </>
              )}
            </div>
          )}
        </div>

        {/* 分页导航 - 仅在编辑状态显示 */}
        {status === 'editing' && pendingSegments.length > 1 && (
          <div className="flex items-center justify-center gap-4 px-4 py-3 border-t border-zinc-700/50 bg-zinc-800/30">
            {/* 上一个按钮 */}
            <button
              onClick={goToPrev}
              disabled={currentIndex === 0}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="上一个 (←)"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>

            {/* 分页指示器 */}
            <div className="flex items-center gap-1.5">
              {pendingSegments.map((ps, idx) => {
                const key = `${ps.taskId}-${ps.segmentIndex}`
                const isModified = editStates[key]?.isModified
                const isCurrent = idx === currentIndex

                return (
                  <button
                    key={key}
                    onClick={() => setCurrentIndex(idx)}
                    className={`w-2.5 h-2.5 rounded-full transition-all ${
                      isCurrent
                        ? 'w-6 bg-blue-500'
                        : isModified
                          ? 'bg-blue-400/60 hover:bg-blue-400'
                          : 'bg-zinc-600 hover:bg-zinc-500'
                    }`}
                    title={`任务${ps.taskIndex + 1} - 段${ps.segmentIndex}${isModified ? ' (已修改)' : ''}`}
                  />
                )
              })}
            </div>

            {/* 下一个按钮 */}
            <button
              onClick={goToNext}
              disabled={currentIndex === pendingSegments.length - 1}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="下一个 (→)"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        )}

        {/* 当前任务信息 - 仅在编辑状态显示 */}
        {status === 'editing' && currentSegment && (
          <div className="flex items-center justify-center px-4 py-2 bg-zinc-800/50 text-xs text-zinc-400">
            <span>
              任务{currentSegment.taskIndex + 1} - 段{currentSegment.segmentIndex}
              <span className="text-zinc-600 mx-2">|</span>
              {currentIndex + 1} / {pendingSegments.length}
            </span>
            {currentEditState.isModified && (
              <span className="ml-3 px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded text-[10px]">
                已修改
              </span>
            )}
          </div>
        )}

        {/* 底部操作 */}
        <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-zinc-700">
          {status === 'editing' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                className="px-5 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors flex items-center gap-2"
              >
                <Play className="w-4 h-4" />
                确认并开始生成 {pendingSegments.length} 个
              </button>
            </>
          )}

          {(status === 'saving' || status === 'generating') && (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
            >
              后台运行
            </button>
          )}

          {status === 'completed' && (
            <button
              onClick={onClose}
              className="px-5 py-2 text-sm bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg transition-colors"
            >
              关闭
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
