import { useEffect, useMemo, useState } from 'react'
import { X, RefreshCw, ListChecks, AlertTriangle, Loader2, CheckCircle2 } from 'lucide-react'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

type ApiJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | string

type ApiJob = {
  id: string
  table_id: string
  kind: string
  status: ApiJobStatus
  created_at: string
  updated_at: string
  record_id?: string | null
  project_id?: string | null
  segment_index?: number | null
  message?: string | null
  error?: string | null
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString()
  } catch {
    return iso
  }
}

function statusMeta(status: ApiJobStatus) {
  const s = String(status)
  if (s === 'queued' || s === 'running') {
    return { label: s === 'queued' ? '排队中' : '生成中', cls: 'bg-blue-500/15 text-blue-300 border-blue-500/30' }
  }
  if (s === 'succeeded') {
    return { label: '已完成', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' }
  }
  if (s === 'failed') {
    return { label: '失败', cls: 'bg-red-500/15 text-red-300 border-red-500/30' }
  }
  return { label: s, cls: 'bg-zinc-500/10 text-zinc-300 border-zinc-500/30' }
}

export function ApiJobQueueDrawer({
  isOpen,
  tableId,
  onClose,
  onSelectTask,
}: {
  isOpen: boolean
  tableId: string
  onClose: () => void
  onSelectTask?: (recordId: string) => void
}) {
  const [loading, setLoading] = useState(false)
  const [jobs, setJobs] = useState<ApiJob[]>([])
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null)

  const title = useMemo(() => {
    const running = jobs.filter(j => j.status === 'running' || j.status === 'queued').length
    return running > 0 ? `API任务队列（进行中 ${running}）` : 'API任务队列'
  }, [jobs])

  const load = async () => {
    if (!tableId) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/batch/jobs?table_id=${encodeURIComponent(tableId)}&limit=50`)
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setJobs(data.jobs || [])
      setLastUpdatedAt(new Date().toLocaleString())
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!isOpen) return
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[60]">
      <div className="absolute inset-0 bg-black/70" onClick={onClose} />

      <div className="absolute right-0 top-0 h-full w-[460px] max-w-[92vw] bg-zinc-950 border-l border-zinc-800 flex flex-col">
        <div className="h-14 px-4 border-b border-zinc-800 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
            <ListChecks className="w-4 h-4 text-zinc-300" />
            {title}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg disabled:opacity-50"
              title="刷新队列"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        <div className="px-4 py-2 text-xs text-zinc-500 flex items-center justify-between border-b border-zinc-800">
          <span>仅展示本次运行期间提交的后台任务（重启后清空）</span>
          <span>{lastUpdatedAt ? `更新于 ${lastUpdatedAt}` : ''}</span>
        </div>

        <div className="flex-1 overflow-auto p-4 space-y-3">
          {error && (
            <div className="p-3 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 text-xs flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 mt-0.5" />
              <div>
                <div className="font-medium">加载失败</div>
                <div className="mt-1 text-red-200/90">{error}</div>
              </div>
            </div>
          )}

          {!error && loading && jobs.length === 0 && (
            <div className="py-10 text-center text-zinc-500 text-sm">
              <Loader2 className="w-6 h-6 animate-spin mx-auto mb-3 text-zinc-500" />
              加载中...
            </div>
          )}

          {!error && !loading && jobs.length === 0 && (
            <div className="py-10 text-center text-zinc-500 text-sm">
              当前没有后台任务
            </div>
          )}

          {jobs.map((j) => {
            const meta = statusMeta(j.status)
            const target = j.record_id ? j.record_id.slice(-6) : '-'
            const seg = typeof j.segment_index === 'number' ? `段${j.segment_index}` : ''
            return (
              <div key={j.id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex items-center px-2 py-0.5 text-[11px] rounded border ${meta.cls}`}>
                        {meta.label}
                      </span>
                      <span className="text-xs text-zinc-300 font-medium truncate">
                        {j.kind === 'edit_and_regenerate' ? '编辑并重新生成' : j.kind}
                        {seg ? ` · ${seg}` : ''}
                      </span>
                    </div>
                    <div className="mt-1 text-[11px] text-zinc-500">
                      目标任务：{target} · 提交时间：{formatTime(j.created_at)}
                    </div>
                    {j.message && (
                      <div className="mt-2 text-xs text-zinc-400 break-words">
                        {j.message}
                      </div>
                    )}
                    {j.error && (
                      <div className="mt-2 text-xs text-red-300 break-words">
                        {j.error}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col items-end gap-2">
                    {j.status === 'succeeded' && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
                    {(j.status === 'queued' || j.status === 'running') && (
                      <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
                    )}
                    {j.record_id && onSelectTask && (
                      <button
                        onClick={() => {
                          onSelectTask(j.record_id!)
                          onClose()
                        }}
                        className="px-2 py-1 text-[11px] rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200"
                        title="定位到任务"
                      >
                        定位
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

