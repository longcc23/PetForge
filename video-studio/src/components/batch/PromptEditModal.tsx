import { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X, Loader2, CheckCircle2, AlertCircle, RotateCcw } from 'lucide-react'
import type { Storyboard } from '@/types'

type ModalStatus = 'editing' | 'generating' | 'success' | 'failed'

// 扩展 Storyboard 类型以包含中文字段
interface ExtendedStoryboard extends Storyboard {
  crucial_zh?: string
  action_zh?: string
  sound_zh?: string
  negative_constraint_zh?: string
}

interface Props {
  isOpen: boolean
  taskId: string
  projectId: string
  segment: ExtendedStoryboard | null
  segmentIndex: number
  inputFrameUrl?: string
  inputFrameLabel?: string
  onClose: () => void
  onSubmit: (updatedFields: {
    crucial: string
    action: string
    sound: string
    negative_constraint: string
    crucial_zh?: string
    action_zh?: string
    sound_zh?: string
    negative_constraint_zh?: string
  }) => Promise<{ success: boolean; submitted?: boolean; videoUrl?: string; error?: string; promptSent?: string }>
}

export function PromptEditModal({
  isOpen,
  taskId: _taskId,
  projectId: _projectId,
  segment,
  segmentIndex,
  inputFrameUrl,
  inputFrameLabel,
  onClose,
  onSubmit
}: Props) {
  const [status, setStatus] = useState<ModalStatus>('editing')
  
  // 英文字段（可编辑）
  const [crucial, setCrucial] = useState('')
  const [action, setAction] = useState('')
  const [sound, setSound] = useState('')
  const [negativeConstraint, setNegativeConstraint] = useState('')
  
  // 中文字段（只读参考）
  const [crucialZh, setCrucialZh] = useState('')
  const [actionZh, setActionZh] = useState('')
  const [soundZh, setSoundZh] = useState('')
  const [negativeConstraintZh, setNegativeConstraintZh] = useState('')
  
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 初始化字段值
  useEffect(() => {
    if (segment && isOpen) {
      setCrucial(segment.crucial || '')
      setAction(segment.action || '')
      setSound(segment.sound || '')
      setNegativeConstraint(segment.negative_constraint || '')
      setCrucialZh(segment.crucial_zh || '')
      setActionZh(segment.action_zh || '')
      setSoundZh(segment.sound_zh || '')
      setNegativeConstraintZh(segment.negative_constraint_zh || '')
      setStatus('editing')
      setVideoUrl(null)
      setError(null)
    }
  }, [segment, isOpen])

  // 处理提交
  const handleSubmit = async () => {
    if (!crucial.trim()) {
      setError('关键画面不能为空')
      return
    }

    setStatus('generating')
    setError(null)

    try {
      const result = await onSubmit({
        crucial: crucial.trim(),
        action: action.trim(),
        sound: sound.trim(),
        negative_constraint: negativeConstraint.trim(),
        crucial_zh: crucialZh,
        action_zh: actionZh,
        sound_zh: soundZh,
        negative_constraint_zh: negativeConstraintZh,
      })

      if (result.submitted) {
        // 已提交到后台队列
        setStatus('success')
        setVideoUrl(null)
      } else if (result.success) {
        setStatus('success')
        setVideoUrl(result.videoUrl || null)
      } else {
        setStatus('failed')
        setError(result.error || '生成失败')
      }
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : '未知错误')
    }
  }

  const handleRetry = () => {
    setStatus('editing')
    setError(null)
  }

  if (!isOpen || !segment) return null

  const modalContent = (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        className="relative bg-zinc-900 rounded-lg overflow-hidden w-full max-w-4xl mx-4 max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
          <h3 className="text-sm font-medium text-zinc-200">
            编辑提示词 - 段{segmentIndex}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-auto p-4">
          {status === 'editing' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* 左侧：首帧预览 */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-medium text-zinc-400">用于生成该段的首帧图</h4>
                  {inputFrameLabel && (
                    <span className="text-[10px] text-zinc-500">{inputFrameLabel}</span>
                  )}
                </div>
                <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg overflow-hidden">
                  {inputFrameUrl ? (
                    <img
                      src={inputFrameUrl}
                      alt="输入首帧"
                      className="w-full h-auto object-contain max-h-[300px]"
                    />
                  ) : (
                    <div className="p-6 text-xs text-zinc-500 text-center">
                      未找到该段的输入首帧
                    </div>
                  )}
                </div>
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
                  <span className="font-medium">提示：</span>编辑英文 prompt，中文仅供参考。
                </div>
              </div>

              {/* 右侧：字段编辑 */}
              <div className="space-y-4">
                {/* 关键画面 */}
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                    关键画面 Crucial <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    value={crucial}
                    onChange={e => setCrucial(e.target.value)}
                    rows={4}
                    className="w-full px-3 py-2 text-sm bg-zinc-800 border border-zinc-600 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 resize-none"
                    placeholder="Describe the key visual elements..."
                  />
                  {crucialZh && (
                    <div className="mt-1.5 px-2 py-1.5 bg-zinc-800/30 border border-zinc-700/30 rounded text-[11px] text-zinc-500">
                      <span className="text-zinc-600 mr-1">参考:</span>{crucialZh}
                    </div>
                  )}
                </div>

                {/* 动作描述 */}
                <div>
                  <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                    动作描述 Action
                  </label>
                  <textarea
                    value={action}
                    onChange={e => setAction(e.target.value)}
                    rows={5}
                    className="w-full px-3 py-2 text-sm bg-zinc-800 border border-zinc-600 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 resize-none"
                    placeholder="Describe the movement and actions..."
                  />
                  {actionZh && (
                    <div className="mt-1.5 px-2 py-1.5 bg-zinc-800/30 border border-zinc-700/30 rounded text-[11px] text-zinc-500">
                      <span className="text-zinc-600 mr-1">参考:</span>{actionZh}
                    </div>
                  )}
                </div>

                {/* 音效描述 */}
                {(sound || soundZh) && (
                  <div>
                    <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                      音效 Sound
                    </label>
                    <textarea
                      value={sound}
                      onChange={e => setSound(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-2 text-sm bg-zinc-800 border border-zinc-600 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 resize-none"
                      placeholder="Sound effects..."
                    />
                    {soundZh && (
                      <div className="mt-1.5 px-2 py-1.5 bg-zinc-800/30 border border-zinc-700/30 rounded text-[11px] text-zinc-500">
                        <span className="text-zinc-600 mr-1">参考:</span>{soundZh}
                      </div>
                    )}
                  </div>
                )}

                {/* 负向约束 */}
                {(negativeConstraint || negativeConstraintZh) && (
                  <div>
                    <label className="block text-xs font-medium text-zinc-400 mb-1.5">
                      负向约束 Negative
                    </label>
                    <textarea
                      value={negativeConstraint}
                      onChange={e => setNegativeConstraint(e.target.value)}
                      rows={2}
                      className="w-full px-3 py-2 text-sm bg-zinc-800 border border-zinc-600 rounded-lg text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 resize-none"
                      placeholder="What to avoid..."
                    />
                    {negativeConstraintZh && (
                      <div className="mt-1.5 px-2 py-1.5 bg-zinc-800/30 border border-zinc-700/30 rounded text-[11px] text-zinc-500">
                        <span className="text-zinc-600 mr-1">参考:</span>{negativeConstraintZh}
                      </div>
                    )}
                  </div>
                )}

                {/* 错误提示 */}
                {error && (
                  <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-300">
                    {error}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 生成中状态 */}
          {status === 'generating' && (
            <div className="flex flex-col items-center justify-center py-16">
              <Loader2 className="w-12 h-12 text-blue-400 animate-spin mb-4" />
              <p className="text-sm text-zinc-300">正在生成视频...</p>
              <p className="text-xs text-zinc-500 mt-1">这可能需要几分钟时间</p>
            </div>
          )}

          {/* 成功状态 */}
          {status === 'success' && (
            <div className="flex flex-col items-center justify-center py-16">
              <CheckCircle2 className="w-12 h-12 text-green-400 mb-4" />
              <p className="text-sm text-zinc-300 mb-2">
                {videoUrl ? '视频生成成功！' : '已提交到后台队列'}
              </p>
              {videoUrl && (
                <video
                  src={videoUrl}
                  controls
                  className="mt-4 max-w-md rounded-lg"
                />
              )}
            </div>
          )}

          {/* 失败状态 */}
          {status === 'failed' && (
            <div className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
              <p className="text-sm text-red-300 mb-2">生成失败</p>
              <p className="text-xs text-zinc-500 mb-4">{error}</p>
            </div>
          )}
        </div>

        {/* 底部操作栏 */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-zinc-700 bg-zinc-900/50">
          {status === 'editing' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSubmit}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors flex items-center gap-2"
              >
                <RotateCcw className="w-4 h-4" />
                确认并重新生成
              </button>
            </>
          )}

          {status === 'success' && (
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm bg-zinc-700 hover:bg-zinc-600 text-white rounded-lg transition-colors"
            >
              关闭
            </button>
          )}

          {status === 'failed' && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors"
              >
                关闭
              </button>
              <button
                onClick={handleRetry}
                className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors flex items-center gap-2"
              >
                <RotateCcw className="w-4 h-4" />
                重新编辑
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )

  // 使用 Portal 渲染到 body，避免被父容器影响
  return createPortal(modalContent, document.body)
}
