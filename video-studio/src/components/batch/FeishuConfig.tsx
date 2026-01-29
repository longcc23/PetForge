import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Link2, CheckCircle2, ExternalLink, Settings } from 'lucide-react'
import type { FeishuConfig as FeishuConfigType, BatchSettings } from '@/types'

interface Props {
  config: FeishuConfigType
  settings: BatchSettings
  onConfigChange: (config: FeishuConfigType) => void
  onSettingsChange: (settings: BatchSettings) => void
  onConnect: () => void
  connecting: boolean
}

export function FeishuConfig({ config, settings, onConfigChange, onSettingsChange, onConnect, connecting }: Props) {
  const [showGuide, setShowGuide] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [driveAuthStatus, setDriveAuthStatus] = useState<{ authorized: boolean } | null>(null)

  const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!config.connected || !config.tableId) return
      try {
        const resp = await fetch(`${API_BASE}/api/batch/drive/oauth/status?table_id=${encodeURIComponent(config.tableId)}`)
        if (!resp.ok) return
        const data = await resp.json()
        if (!cancelled) setDriveAuthStatus({ authorized: !!data.authorized })
      } catch {
        // ignore
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [API_BASE, config.connected, config.tableId])

  const handleDriveUserAuth = () => {
    if (!config.tableId) return
    const url = `${API_BASE}/api/batch/drive/oauth/start?table_id=${encodeURIComponent(config.tableId)}`
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="space-y-4">
      {/* 飞书连接 */}
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <Link2 className="w-4 h-4" />
          飞书连接
        </h3>

        {/* 连接状态 */}
        {config.connected ? (
          <div className="space-y-3">
            {/* 连接成功提示 */}
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg">
              <div className="flex items-center gap-2 text-emerald-400 text-sm">
                <CheckCircle2 className="w-4 h-4" />
                已连接
              </div>
              <div className="mt-2 text-xs text-zinc-400">
                <p>表格：{config.tableName}</p>
                <p>记录数：{config.recordCount}</p>
              </div>
            </div>

            {/* 已连接时显示配置字段（置灰，只读） */}
            <div className="space-y-3 opacity-60">
              {/* App ID */}
              <div>
                <label className="block text-xs text-zinc-500 mb-1">App ID</label>
                <input
                  type="text"
                  value={config.appId}
                  disabled
                  className="w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 rounded-lg text-sm text-zinc-400 cursor-not-allowed"
                />
              </div>

              {/* App Secret */}
              <div>
                <label className="block text-xs text-zinc-500 mb-1">App Secret</label>
                <input
                  type="password"
                  value={config.appSecret ? '••••••••' : ''}
                  disabled
                  className="w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 rounded-lg text-sm text-zinc-400 cursor-not-allowed"
                />
              </div>

              {/* Table ID */}
              <div>
                <label className="block text-xs text-zinc-500 mb-1">Table ID</label>
                <input
                  type="text"
                  value={config.tableId}
                  disabled
                  className="w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 rounded-lg text-sm text-zinc-400 cursor-not-allowed"
                />
              </div>

              {/* 云空间文件夹 Token */}
              {config.driveFolderToken && (
                <div>
                  <label className="block text-xs text-zinc-500 mb-1">云空间文件夹</label>
                  <input
                    type="text"
                    value={config.driveFolderToken}
                    disabled
                    className="w-full px-3 py-2 bg-zinc-800/50 border border-zinc-700/50 rounded-lg text-sm text-zinc-400 cursor-not-allowed"
                  />
                </div>
              )}
            </div>

            {/* 云空间授权 */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleDriveUserAuth}
                className="px-3 py-1.5 text-xs rounded-md bg-orange-600 hover:bg-orange-500 text-white"
              >
                云空间用户授权
              </button>
              {driveAuthStatus?.authorized ? (
                <span className="text-xs text-emerald-400">已授权</span>
              ) : (
                <span className="text-xs text-zinc-400">未授权（同步云空间前需要）</span>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {/* App ID */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">App ID</label>
              <input
                type="text"
                value={config.appId}
                onChange={(e) => onConfigChange({ ...config, appId: e.target.value })}
                placeholder="cli_xxxxxxxx"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* App Secret */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">App Secret</label>
              <input
                type="text"
                value={config.appSecret}
                onChange={(e) => onConfigChange({ ...config, appSecret: e.target.value })}
                placeholder="输入 App Secret"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* App Token */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">
                App Token <span className="text-zinc-600">(可选)</span>
              </label>
              <input
                type="text"
                value={config.appToken || ''}
                onChange={(e) => onConfigChange({ ...config, appToken: e.target.value })}
                placeholder="appxxxxxxxx 或留空（如果 Table ID 是完整格式）"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
              />
              <p className="mt-1 text-xs text-zinc-600">
                如果 Table ID 是 "appXXXXX/tblYYYYY" 格式，可留空
              </p>
            </div>

            {/* Tenant Access Token (调试用) */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">
                Tenant Access Token <span className="text-zinc-600">(可选，调试用)</span>
              </label>
              <input
                type="text"
                value={config.tenantAccessToken || ''}
                onChange={(e) => onConfigChange({ ...config, tenantAccessToken: e.target.value })}
                placeholder="直接使用提供的 token（用于调试）"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
              />
              <p className="mt-1 text-xs text-zinc-600">
                如果提供，将直接使用此 token 而不是通过 App ID/Secret 获取
              </p>
            </div>

            {/* Table ID */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">Table ID</label>
              <input
                type="text"
                value={config.tableId}
                onChange={(e) => onConfigChange({ ...config, tableId: e.target.value })}
                placeholder="tblxxxxxxxx 或 appXXXXX/tblYYYYY"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* 云空间文件夹 Token */}
            <div>
              <label className="block text-xs text-zinc-500 mb-1">
                云空间文件夹 Token <span className="text-zinc-600">(可选，用于同步文件)</span>
              </label>
              <input
                type="text"
                value={config.driveFolderToken || ''}
                onChange={(e) => onConfigChange({ ...config, driveFolderToken: e.target.value })}
                placeholder="LO1jf6cT7lOEuXdHYXScSV8Vnth"
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-orange-500"
              />
              <p className="mt-1 text-xs text-zinc-600">
                从飞书云空间文件夹 URL 中获取，用于上传项目文件
              </p>
            </div>

            {/* 连接按钮 */}
            <button
              onClick={onConnect}
              disabled={connecting || !config.appId || !config.appSecret || !config.tableId}
              className="w-full py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {connecting ? '连接中...' : '测试连接'}
            </button>
          </div>
        )}

        {/* 配置引导 */}
        <button
          onClick={() => setShowGuide(!showGuide)}
          className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
        >
          {showGuide ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          如何获取飞书应用凭证？
        </button>

        {showGuide && (
          <div className="p-3 bg-zinc-800/50 border border-zinc-700 rounded-lg text-xs text-zinc-400 space-y-2">
            <ol className="list-decimal list-inside space-y-1.5">
              <li>
                访问{' '}
                <a href="https://open.feishu.cn/" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline inline-flex items-center gap-0.5">
                  飞书开放平台 <ExternalLink className="w-3 h-3" />
                </a>{' '}
                创建企业自建应用
              </li>
              <li>在「凭证与基础信息」获取 App ID 和 App Secret</li>
              <li>
                在「权限管理」添加权限：
                <ul className="ml-4 mt-1 text-zinc-500">
                  <li>• bitable:app（多维表格读写）</li>
                  <li>• drive:drive（云空间访问，用于上传文件）</li>
                </ul>
              </li>
              <li>发布应用并授权给目标多维表格</li>
            </ol>
            <a
              href="https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview"
              target="_blank"
              rel="noopener noreferrer"
              className="block text-blue-400 hover:underline mt-2"
            >
              查看官方文档 →
            </a>
          </div>
        )}
      </div>

      {/* 高级设置 */}
      <div className="pt-4 border-t border-zinc-800">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-2 text-sm text-zinc-400 hover:text-zinc-300"
        >
          <Settings className="w-4 h-4" />
          高级设置
          {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </button>

        {showAdvanced && (
          <div className="mt-3 space-y-3">
            {/* 分镜并发 */}
            <div>
              <label className="flex justify-between text-xs text-zinc-500 mb-1">
                <span>分镜生成并发数</span>
                <span className="text-zinc-400">{settings.storyboardConcurrency}</span>
              </label>
              <input
                type="range"
                min="1"
                max="20"
                value={settings.storyboardConcurrency}
                onChange={(e) => onSettingsChange({ ...settings, storyboardConcurrency: Number(e.target.value) })}
                className="w-full h-1.5 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-zinc-600 mt-0.5">
                <span>1</span>
                <span>20</span>
              </div>
            </div>

            {/* 视频并发 */}
            <div>
              <label className="flex justify-between text-xs text-zinc-500 mb-1">
                <span>视频生成并发数</span>
                <span className="text-zinc-400">{settings.videoConcurrency}</span>
              </label>
              <input
                type="range"
                min="1"
                max="10"
                value={settings.videoConcurrency}
                onChange={(e) => onSettingsChange({ ...settings, videoConcurrency: Number(e.target.value) })}
                className="w-full h-1.5 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-zinc-600 mt-0.5">
                <span>1</span>
                <span>10</span>
              </div>
            </div>

            {/* 回写批次 */}
            <div>
              <label className="flex justify-between text-xs text-zinc-500 mb-1">
                <span>回写批次大小</span>
                <span className="text-zinc-400">{settings.writebackBatchSize}</span>
              </label>
              <input
                type="range"
                min="100"
                max="500"
                step="50"
                value={settings.writebackBatchSize}
                onChange={(e) => onSettingsChange({ ...settings, writebackBatchSize: Number(e.target.value) })}
                className="w-full h-1.5 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
              />
              <div className="flex justify-between text-xs text-zinc-600 mt-0.5">
                <span>100</span>
                <span>500</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
