import { CheckCircle2, Clock, Loader2, AlertCircle } from 'lucide-react'
import type { BatchStats } from '@/types'

interface Props {
  stats: BatchStats
}

export function StatsBar({ stats }: Props) {
  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg p-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        {/* 统计数字 */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-zinc-400" />
            <span className="text-sm text-zinc-400">总数</span>
            <span className="text-lg font-semibold text-zinc-200">{stats.total}</span>
          </div>

          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span className="text-sm text-zinc-400">已完成</span>
            <span className="text-lg font-semibold text-emerald-400">{stats.completed}</span>
          </div>

          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 text-blue-400" />
            <span className="text-sm text-zinc-400">进行中</span>
            <span className="text-lg font-semibold text-blue-400">{stats.inProgress}</span>
          </div>

          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-400" />
            <span className="text-sm text-zinc-400">失败</span>
            <span className="text-lg font-semibold text-red-400">{stats.failed}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
