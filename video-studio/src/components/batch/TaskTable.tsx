import { useMemo, useState, useRef, useEffect } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type RowSelectionState,
} from '@tanstack/react-table'
import {
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  Upload,
  ChevronUp,
  ChevronDown,
  Play,
  Image as ImageIcon,
  Check,
  Square
} from 'lucide-react'
import type { BatchTask, BatchTaskStatus } from '@/types'

interface Props {
  tasks: BatchTask[]
  selectedTaskId: string | null
  onSelectTask: (taskId: string | null) => void
  onUploadImage: (taskId: string, file: File) => void
  statusFilter: BatchTaskStatus | 'all'
  onStatusFilterChange: (status: BatchTaskStatus | 'all') => void
  onSelectionChange?: (selectedIds: string[]) => void
}

const columnHelper = createColumnHelper<BatchTask>()

// API 基础路径（用于拼接 /storage、/proxy/image 等相对路径资源）
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'
const resolveMediaUrl = (url?: string) => {
  if (!url) return undefined
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  if (url.startsWith('/')) return `${API_BASE}${url}`
  return url
}

// 状态配置
const STATUS_CONFIG: Record<BatchTaskStatus, { label: string; color: string; icon: typeof CheckCircle2 }> = {
  pending: { label: '待处理', color: 'text-zinc-400 bg-zinc-700', icon: Clock },
  storyboard_generating: { label: '分镜生成中', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  storyboard_ready: { label: '分镜已生成', color: 'text-cyan-400 bg-cyan-500/20', icon: CheckCircle2 },
  generating_segment_0: { label: '生成段0', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_1: { label: '生成段1', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_2: { label: '生成段2', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_3: { label: '生成段3', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_4: { label: '生成段4', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_5: { label: '生成段5', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  generating_segment_6: { label: '生成段6', color: 'text-blue-400 bg-blue-500/20', icon: Loader2 },
  all_segments_ready: { label: '待合并', color: 'text-purple-400 bg-purple-500/20', icon: CheckCircle2 },
  merging: { label: '合并中', color: 'text-purple-400 bg-purple-500/20', icon: Loader2 },
  completed: { label: '已完成', color: 'text-emerald-400 bg-emerald-500/20', icon: CheckCircle2 },
  failed: { label: '失败', color: 'text-red-400 bg-red-500/20', icon: AlertCircle },
  image_failed: { label: '首帧失败', color: 'text-orange-400 bg-orange-500/20', icon: AlertCircle },
}

// 分段状态图标
function SegmentStatus({ status }: { status: 'pending' | 'generating' | 'completed' | 'failed' }) {
  if (status === 'completed') return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
  if (status === 'generating') return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
  if (status === 'failed') return <AlertCircle className="w-4 h-4 text-red-400" />
  return <Clock className="w-4 h-4 text-zinc-500" />
}

export function TaskTable({
  tasks,
  selectedTaskId,
  onSelectTask,
  onUploadImage,
  statusFilter,
  onStatusFilterChange,
  onSelectionChange
}: Props) {
  const [sorting, setSorting] = useState<SortingState>([])
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploadingTaskId, setUploadingTaskId] = useState<string | null>(null)

  // 同步 rowSelection 到父组件
  const selectedIds = useMemo(() => {
    return Object.keys(rowSelection).filter(key => rowSelection[key])
  }, [rowSelection])

  useEffect(() => {
    onSelectionChange?.(selectedIds)
  }, [selectedIds, onSelectionChange])

  // 处理文件上传
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && uploadingTaskId) {
      onUploadImage(uploadingTaskId, file)
      setUploadingTaskId(null)
    }
    e.target.value = ''
  }

  const triggerUpload = (taskId: string) => {
    setUploadingTaskId(taskId)
    fileInputRef.current?.click()
  }

  const columns = useMemo(() => [
    // 复选框列
    columnHelper.display({
      id: 'select',
      header: ({ table }) => (
        <button
          onClick={(e) => {
            e.stopPropagation()
            table.toggleAllRowsSelected(!table.getIsAllRowsSelected())
          }}
          className="p-1 hover:bg-zinc-700 rounded transition-colors"
          title={table.getIsAllRowsSelected() ? '取消全选' : '全选'}
        >
          {table.getIsAllRowsSelected() ? (
            <Check className="w-4 h-4 text-pink-400" />
          ) : (
            <Square className="w-4 h-4 text-zinc-500" />
          )}
        </button>
      ),
      cell: ({ row }) => (
        <button
          onClick={(e) => {
            e.stopPropagation()
            row.toggleSelected()
          }}
          className="p-1 hover:bg-zinc-700 rounded transition-colors"
          title={row.getIsSelected() ? '取消选中' : '选中'}
        >
          {row.getIsSelected() ? (
            <Check className="w-4 h-4 text-pink-400" />
          ) : (
            <Square className="w-4 h-4 text-zinc-500" />
          )}
        </button>
      ),
      size: 40,
    }),

    // project ID（项目ID）
    columnHelper.accessor('projectId', {
      header: 'project ID',
      cell: ({ getValue }) => {
        const projectId = getValue()
        const short = projectId ? projectId.slice(-6) : '-'
        return (
          <span className="text-xs text-zinc-400 font-mono max-w-[52px] inline-block truncate" title={projectId || ''}>
            {short}
          </span>
        )
      },
      size: 80,
    }),

    // 发布日期（publishDate）
    columnHelper.accessor('publishDate', {
      header: '发布日期',
      cell: ({ getValue }) => {
        const publishDate = getValue()
        if (!publishDate || String(publishDate).trim().length === 0) {
          return (
            <span className="text-xs text-zinc-400 max-w-[80px] inline-block truncate">-</span>
          )
        }
        // 格式化日期：YYYYMMDD -> YYYY-MM-DD
        const dateStr = String(publishDate).trim()
        let formattedDate = dateStr
        if (dateStr.length === 8 && /^\d{8}$/.test(dateStr)) {
          // YYYYMMDD 格式
          formattedDate = `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
        }
        return (
          <span className="text-xs text-zinc-400 max-w-[80px] inline-block truncate" title={formattedDate}>
            {formattedDate}
          </span>
        )
      },
      size: 100,
    }),

    // 首帧预览
    columnHelper.accessor('openingImageUrl', {
      header: '首帧',
      cell: ({ row, getValue }) => {
        const task = row.original
        const status = task.status

        if (status === 'image_failed') {
          return (
            <button
              onClick={(e) => {
                e.stopPropagation()
                triggerUpload(task.id)
              }}
              className="w-12 h-12 rounded bg-zinc-800 border border-dashed border-orange-500/50 flex items-center justify-center hover:border-orange-400 transition-colors"
              title="上传首帧图片"
            >
              <Upload className="w-4 h-4 text-orange-400" />
            </button>
          )
        }

        // 优先使用 openingImageUrl，如果没有则兜底到项目目录
        const url = resolveMediaUrl(getValue()) || 
          (task.projectId ? `${API_BASE}/storage/projects/${task.projectId}/opening_image.jpg` : undefined)

        if (url) {
          return (
            <img
              src={url}
              alt="首帧"
              className="w-12 h-12 rounded object-cover"
              onError={(e) => {
                // 如果图片加载失败，显示占位符
                e.currentTarget.style.display = 'none'
                const parent = e.currentTarget.parentElement
                if (parent) {
                  parent.innerHTML = '<div class="w-12 h-12 rounded bg-zinc-800 flex items-center justify-center"><svg class="w-4 h-4 text-zinc-600" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="2" y1="7" x2="7" y2="7"/><line x1="2" y1="17" x2="7" y2="17"/><line x1="17" y1="17" x2="22" y2="17"/><line x1="17" y1="7" x2="22" y2="7"/></svg></div>'
                }
              }}
            />
          )
        }

        return (
          <div className="w-12 h-12 rounded bg-zinc-800 flex items-center justify-center">
            <ImageIcon className="w-4 h-4 text-zinc-600" />
          </div>
        )
      },
      size: 60,
    }),

    // 状态
    columnHelper.accessor('status', {
      header: '状态',
      cell: ({ getValue }) => {
        const status = getValue()
        const config = STATUS_CONFIG[status]
        const Icon = config.icon
        const isAnimated = status.includes('generating') || status === 'merging' || status === 'storyboard_generating'

        return (
          <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${config.color}`}>
            <Icon className={`w-3 h-3 ${isAnimated ? 'animate-spin' : ''}`} />
            {config.label}
          </span>
        )
      },
      size: 100,
    }),

    // 分镜
    columnHelper.accessor('storyboardJson', {
      header: '分镜',
      cell: ({ getValue, row }) => {
        const json = getValue()
        const status = row.original.status

        if (json) {
          return <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        }
        if (status === 'storyboard_generating') {
          return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
        }
        return <Clock className="w-4 h-4 text-zinc-500" />
      },
      size: 50,
    }),

    // 动态分段列（最多显示7段）
    ...Array.from({ length: 7 }, (_, i) =>
      columnHelper.display({
        id: `segment_${i}`,
        header: `段${i}`,
        cell: ({ row }) => {
          const segment = row.original.segments[i]
          if (!segment) return <span className="text-zinc-700">-</span>
          return <SegmentStatus status={segment.status} />
        },
        size: 45,
      })
    ),

    // 最终视频
    columnHelper.accessor('finalVideoUrl', {
      header: '最终',
      cell: ({ getValue, row }) => {
        const url = resolveMediaUrl(getValue())
        const status = row.original.status

        if (url) {
          return (
            <button
              onClick={(e) => {
                e.stopPropagation()
                window.open(url, '_blank')
              }}
              className="text-emerald-400 hover:text-emerald-300"
              title="播放视频"
            >
              <Play className="w-4 h-4" />
            </button>
          )
        }
        if (status === 'merging') {
          return <Loader2 className="w-4 h-4 text-purple-400 animate-spin" />
        }
        return <Clock className="w-4 h-4 text-zinc-500" />
      },
      size: 50,
    }),

    // 进度
    columnHelper.accessor('progress', {
      header: '进度',
      cell: ({ getValue }) => (
        <span className="text-xs text-zinc-400">{getValue() || '-'}</span>
      ),
      size: 80,
    }),
  ], [])

  // 筛选后的数据
  const filteredData = useMemo(() => {
    if (statusFilter === 'all') return tasks
    return tasks.filter(t => t.status === statusFilter)
  }, [tasks, statusFilter])

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getRowId: (row) => row.id,  // 使用 task.id 作为行标识，而不是行索引
  })

  return (
    <div className="flex flex-col h-full">
      {/* 隐藏的文件输入 */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* 筛选栏 */}
      <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-zinc-500">筛选：</span>
          {(['all', 'pending', 'storyboard_ready', 'completed', 'failed'] as const).map((status) => (
            <button
              key={status}
              onClick={() => onStatusFilterChange(status)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                statusFilter === status
                  ? 'bg-blue-600 text-white'
                  : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'
              }`}
            >
              {status === 'all' ? '全部' : STATUS_CONFIG[status]?.label || status}
            </button>
          ))}
        </div>

        {/* 多选操作按钮 */}
        {filteredData.length > 0 && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                const allSelected = table.getIsAllRowsSelected()
                table.toggleAllRowsSelected(!allSelected)
              }}
              className="px-2 py-1 text-xs rounded bg-zinc-800 text-zinc-400 hover:bg-zinc-700 transition-colors"
            >
              全选
            </button>
            <button
              onClick={() => {
                const newSelection: RowSelectionState = {}
                table.getRowModel().rows.forEach(row => {
                  newSelection[row.id] = !row.getIsSelected()
                })
                setRowSelection(newSelection)
              }}
              className="px-2 py-1 text-xs rounded bg-zinc-800 text-zinc-400 hover:bg-zinc-700 transition-colors"
            >
              反选
            </button>
            <span className="text-xs text-zinc-500">
              已选择: {selectedIds.length}/{filteredData.length} 条
            </span>
          </div>
        )}
      </div>

      {/* 表格 */}
      <div className="flex-1 overflow-auto rounded-lg border border-zinc-800">
        <table className="w-full">
          <thead className="bg-zinc-900 sticky top-0">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="px-3 py-2 text-left text-xs font-medium text-zinc-500 border-b border-zinc-800"
                    style={{ width: header.getSize() }}
                  >
                    {header.isPlaceholder ? null : (
                      <div
                        className={header.column.getCanSort() ? 'cursor-pointer select-none flex items-center gap-1' : ''}
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {{
                          asc: <ChevronUp className="w-3 h-3" />,
                          desc: <ChevronDown className="w-3 h-3" />,
                        }[header.column.getIsSorted() as string] ?? null}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-8 text-center text-zinc-500 text-sm">
                  暂无任务数据
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => onSelectTask(row.original.id)}
                  className={`border-b border-zinc-800/50 cursor-pointer transition-colors ${
                    row.getIsSelected()
                      ? 'bg-pink-500/20'
                      : selectedTaskId === row.original.id
                        ? 'bg-blue-600/10'
                        : 'hover:bg-zinc-800/50'
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-3 py-2 text-sm text-zinc-300">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
