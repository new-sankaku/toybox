import { useState } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import {
  Image,
  Music,
  FileText,
  Code,
  Download,
  Play,
  Pause,
  Eye,
  X,
  FolderOpen,
  Grid,
  List,
  Check,
  XCircle,
  Filter
} from 'lucide-react'

type AssetType = 'image' | 'audio' | 'document' | 'code' | 'other'
type ViewMode = 'grid' | 'list'
type ApprovalStatus = 'approved' | 'pending' | 'rejected'
type ApprovalFilter = 'all' | 'approved' | 'pending' | 'rejected'

interface Asset {
  id: string
  name: string
  type: AssetType
  agent: string
  size: string
  createdAt: string
  url?: string
  thumbnail?: string
  duration?: string
  approvalStatus: ApprovalStatus
}

// Mock assets data
const initialMockAssets: Asset[] = [
  {
    id: '1',
    name: 'player_sprite.png',
    type: 'image',
    agent: 'AssetLeader',
    size: '245 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    url: 'https://via.placeholder.com/256x256/4A7C59/FFFFFF?text=Player',
    thumbnail: 'https://via.placeholder.com/128x128/4A7C59/FFFFFF?text=Player',
    approvalStatus: 'approved'
  },
  {
    id: '2',
    name: 'enemy_goblin.png',
    type: 'image',
    agent: 'AssetLeader',
    size: '180 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    url: 'https://via.placeholder.com/256x256/8B4513/FFFFFF?text=Goblin',
    thumbnail: 'https://via.placeholder.com/128x128/8B4513/FFFFFF?text=Goblin',
    approvalStatus: 'pending'
  },
  {
    id: '3',
    name: 'tileset_forest.png',
    type: 'image',
    agent: 'AssetLeader',
    size: '512 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    url: 'https://via.placeholder.com/512x512/228B22/FFFFFF?text=Forest+Tiles',
    thumbnail: 'https://via.placeholder.com/128x128/228B22/FFFFFF?text=Forest',
    approvalStatus: 'approved'
  },
  {
    id: '4',
    name: 'ui_buttons.png',
    type: 'image',
    agent: 'AssetLeader',
    size: '89 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
    url: 'https://via.placeholder.com/256x128/4169E1/FFFFFF?text=UI+Buttons',
    thumbnail: 'https://via.placeholder.com/128x64/4169E1/FFFFFF?text=Buttons',
    approvalStatus: 'pending'
  },
  {
    id: '5',
    name: 'main_theme.mp3',
    type: 'audio',
    agent: 'AssetLeader',
    size: '3.2 MB',
    createdAt: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    duration: '2:45',
    approvalStatus: 'approved'
  },
  {
    id: '6',
    name: 'battle_bgm.mp3',
    type: 'audio',
    agent: 'AssetLeader',
    size: '2.8 MB',
    createdAt: new Date(Date.now() - 1000 * 60 * 150).toISOString(),
    duration: '3:12',
    approvalStatus: 'pending'
  },
  {
    id: '7',
    name: 'sfx_attack.wav',
    type: 'audio',
    agent: 'AssetLeader',
    size: '156 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 180).toISOString(),
    duration: '0:02',
    approvalStatus: 'rejected'
  },
  {
    id: '8',
    name: 'sfx_jump.wav',
    type: 'audio',
    agent: 'AssetLeader',
    size: '98 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 200).toISOString(),
    duration: '0:01',
    approvalStatus: 'approved'
  },
  {
    id: '9',
    name: 'concept_document.md',
    type: 'document',
    agent: 'Concept',
    size: '12.5 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 240).toISOString(),
    approvalStatus: 'approved'
  },
  {
    id: '10',
    name: 'game_design.md',
    type: 'document',
    agent: 'Design',
    size: '18.2 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 300).toISOString(),
    approvalStatus: 'pending'
  },
  {
    id: '11',
    name: 'player_controller.ts',
    type: 'code',
    agent: 'CodeLeader',
    size: '4.5 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 360).toISOString(),
    approvalStatus: 'approved'
  },
  {
    id: '12',
    name: 'game_state.ts',
    type: 'code',
    agent: 'CodeLeader',
    size: '6.2 KB',
    createdAt: new Date(Date.now() - 1000 * 60 * 400).toISOString(),
    approvalStatus: 'pending'
  }
]

const approvalStatusLabels: Record<ApprovalStatus, string> = {
  approved: '承認済',
  pending: '未承認',
  rejected: '却下'
}

const approvalStatusColors: Record<ApprovalStatus, string> = {
  approved: 'text-nier-accent-green',
  pending: 'text-nier-accent-orange',
  rejected: 'text-nier-accent-red'
}

const approvalBgColors: Record<ApprovalStatus, string> = {
  approved: 'bg-nier-accent-green/20 border-nier-accent-green',
  pending: 'bg-nier-accent-orange/20 border-nier-accent-orange',
  rejected: 'bg-nier-accent-red/20 border-nier-accent-red'
}

const typeIcons: Record<AssetType, typeof Image> = {
  image: Image,
  audio: Music,
  document: FileText,
  code: Code,
  other: FolderOpen
}

const typeLabels: Record<AssetType, string> = {
  image: '画像',
  audio: '音声',
  document: 'ドキュメント',
  code: 'コード',
  other: 'その他'
}

const typeColors: Record<AssetType, string> = {
  image: 'text-nier-accent-green',
  audio: 'text-nier-accent-orange',
  document: 'text-nier-accent-blue',
  code: 'text-nier-accent-yellow',
  other: 'text-nier-text-light'
}

export default function DataView(): JSX.Element {
  const [assets, setAssets] = useState<Asset[]>(initialMockAssets)
  const [filterType, setFilterType] = useState<AssetType | 'all'>('all')
  const [approvalFilter, setApprovalFilter] = useState<ApprovalFilter>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null)
  const [playingAudio, setPlayingAudio] = useState<string | null>(null)

  const filteredAssets = assets
    .filter(a => filterType === 'all' || a.type === filterType)
    .filter(a => approvalFilter === 'all' || a.approvalStatus === approvalFilter)

  const assetCounts = {
    all: assets.length,
    image: assets.filter(a => a.type === 'image').length,
    audio: assets.filter(a => a.type === 'audio').length,
    document: assets.filter(a => a.type === 'document').length,
    code: assets.filter(a => a.type === 'code').length
  }

  const approvalCounts = {
    all: assets.length,
    approved: assets.filter(a => a.approvalStatus === 'approved').length,
    pending: assets.filter(a => a.approvalStatus === 'pending').length,
    rejected: assets.filter(a => a.approvalStatus === 'rejected').length
  }

  const handlePlayAudio = (assetId: string) => {
    if (playingAudio === assetId) {
      setPlayingAudio(null)
    } else {
      setPlayingAudio(assetId)
    }
  }

  const handleApprove = (assetId: string) => {
    setAssets(assets.map(a =>
      a.id === assetId ? { ...a, approvalStatus: 'approved' as ApprovalStatus } : a
    ))
    if (selectedAsset?.id === assetId) {
      setSelectedAsset({ ...selectedAsset, approvalStatus: 'approved' })
    }
  }

  const handleReject = (assetId: string) => {
    setAssets(assets.map(a =>
      a.id === assetId ? { ...a, approvalStatus: 'rejected' as ApprovalStatus } : a
    ))
    if (selectedAsset?.id === assetId) {
      setSelectedAsset({ ...selectedAsset, approvalStatus: 'rejected' })
    }
  }

  const handleSetPending = (assetId: string) => {
    setAssets(assets.map(a =>
      a.id === assetId ? { ...a, approvalStatus: 'pending' as ApprovalStatus } : a
    ))
    if (selectedAsset?.id === assetId) {
      setSelectedAsset({ ...selectedAsset, approvalStatus: 'pending' })
    }
  }

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-nier-accent-blue" />
          <h1 className="text-nier-h1 font-medium tracking-nier-wide">
            DATA
          </h1>
          <span className="text-nier-text-light">
            - アセット管理
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode('grid')}
            className={cn(
              'p-2 transition-colors',
              viewMode === 'grid' ? 'bg-nier-bg-selected' : 'hover:bg-nier-bg-hover'
            )}
          >
            <Grid size={16} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={cn(
              'p-2 transition-colors',
              viewMode === 'list' ? 'bg-nier-bg-selected' : 'hover:bg-nier-bg-hover'
            )}
          >
            <List size={16} />
          </button>
        </div>
      </div>

      {/* Filter Tabs */}
      <Card className="mb-6">
        <CardContent className="py-2">
          <div className="flex items-center justify-between">
            {/* Type Filter */}
            <div className="flex items-center gap-1">
              {(['all', 'image', 'audio', 'document', 'code'] as const).map(type => {
                const Icon = type === 'all' ? FolderOpen : typeIcons[type]
                const label = type === 'all' ? 'すべて' : typeLabels[type]
                const count = assetCounts[type]
                return (
                  <button
                    key={type}
                    className={cn(
                      'flex items-center gap-2 px-4 py-2 text-nier-small tracking-nier transition-colors',
                      filterType === type
                        ? 'bg-nier-bg-selected text-nier-text-main'
                        : 'text-nier-text-light hover:bg-nier-bg-panel'
                    )}
                    onClick={() => setFilterType(type)}
                  >
                    <Icon size={14} />
                    {label}
                    <span className="text-nier-caption opacity-70">({count})</span>
                  </button>
                )
              })}
            </div>

            {/* Approval Filter */}
            <div className="flex items-center gap-1 border-l border-nier-border-light pl-4">
              <Filter size={14} className="text-nier-text-light mr-2" />
              {(['all', 'pending', 'approved', 'rejected'] as const).map(status => {
                const label = status === 'all' ? '全状態' : approvalStatusLabels[status]
                const count = approvalCounts[status]
                return (
                  <button
                    key={status}
                    className={cn(
                      'px-3 py-1.5 text-nier-small tracking-nier transition-colors border',
                      approvalFilter === status
                        ? status === 'all'
                          ? 'bg-nier-bg-selected border-nier-text-main'
                          : approvalBgColors[status]
                        : 'border-transparent text-nier-text-light hover:bg-nier-bg-panel'
                    )}
                    onClick={() => setApprovalFilter(status)}
                  >
                    {label}
                    <span className="text-nier-caption opacity-70 ml-1">({count})</span>
                  </button>
                )
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Asset Grid/List */}
      {viewMode === 'grid' ? (
        <div className="grid grid-cols-4 gap-4">
          {filteredAssets.map(asset => {
            const Icon = typeIcons[asset.type]
            return (
              <Card
                key={asset.id}
                className="cursor-pointer hover:border-nier-accent-gold transition-colors"
                onClick={() => setSelectedAsset(asset)}
              >
                <CardContent className="p-3">
                  {/* Thumbnail / Icon */}
                  <div className="aspect-square bg-nier-bg-header mb-3 flex items-center justify-center overflow-hidden">
                    {asset.type === 'image' && asset.thumbnail ? (
                      <img
                        src={asset.thumbnail}
                        alt={asset.name}
                        className="w-full h-full object-cover"
                      />
                    ) : asset.type === 'audio' ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handlePlayAudio(asset.id)
                        }}
                        className="w-16 h-16 rounded-full bg-nier-bg-main border-2 border-nier-accent-orange flex items-center justify-center hover:bg-nier-bg-selected transition-colors"
                      >
                        {playingAudio === asset.id ? (
                          <Pause size={24} className="text-nier-accent-orange" />
                        ) : (
                          <Play size={24} className="text-nier-accent-orange ml-1" />
                        )}
                      </button>
                    ) : (
                      <Icon size={48} className={typeColors[asset.type]} />
                    )}
                  </div>

                  {/* Info */}
                  <div className="text-nier-small font-medium truncate" title={asset.name}>
                    {asset.name}
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className={cn('text-nier-caption', typeColors[asset.type])}>
                      {typeLabels[asset.type]}
                    </span>
                    <span className="text-nier-caption text-nier-text-light">
                      {asset.size}
                    </span>
                  </div>
                  {asset.duration && (
                    <div className="text-nier-caption text-nier-text-light mt-1">
                      {asset.duration}
                    </div>
                  )}

                  {/* Approval Status & Buttons */}
                  <div className="mt-2 pt-2 border-t border-nier-border-light">
                    <div className="flex items-center justify-between">
                      <span className={cn('text-nier-caption px-1.5 py-0.5 border', approvalBgColors[asset.approvalStatus])}>
                        {approvalStatusLabels[asset.approvalStatus]}
                      </span>
                      <div className="flex items-center gap-1">
                        {asset.approvalStatus !== 'approved' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleApprove(asset.id)
                            }}
                            className="p-1 hover:bg-nier-accent-green/20 transition-colors text-nier-accent-green"
                            title="承認"
                          >
                            <Check size={14} />
                          </button>
                        )}
                        {asset.approvalStatus !== 'rejected' && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleReject(asset.id)
                            }}
                            className="p-1 hover:bg-nier-accent-red/20 transition-colors text-nier-accent-red"
                            title="却下"
                          >
                            <XCircle size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      ) : (
        <Card>
          <CardHeader>
            <DiamondMarker>アセット一覧</DiamondMarker>
            <span className="text-nier-caption text-nier-text-light ml-auto">
              {filteredAssets.length}件
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <table className="w-full">
              <thead className="bg-nier-bg-header text-nier-text-header">
                <tr>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">ファイル名</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">タイプ</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">状態</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">エージェント</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">サイズ</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">作成日時</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-nier-border-light">
                {filteredAssets.map(asset => {
                  const Icon = typeIcons[asset.type]
                  return (
                    <tr key={asset.id} className="hover:bg-nier-bg-panel transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Icon size={14} className={typeColors[asset.type]} />
                          <span className="text-nier-small">{asset.name}</span>
                        </div>
                      </td>
                      <td className={cn('px-4 py-3 text-nier-small', typeColors[asset.type])}>
                        {typeLabels[asset.type]}
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn('text-nier-caption px-1.5 py-0.5 border', approvalBgColors[asset.approvalStatus])}>
                          {approvalStatusLabels[asset.approvalStatus]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-nier-small text-nier-text-light">
                        {asset.agent}
                      </td>
                      <td className="px-4 py-3 text-nier-small text-nier-text-light">
                        {asset.size}
                        {asset.duration && ` (${asset.duration})`}
                      </td>
                      <td className="px-4 py-3 text-nier-small text-nier-text-light">
                        {new Date(asset.createdAt).toLocaleString('ja-JP')}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setSelectedAsset(asset)}
                            className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-accent-blue"
                            title="プレビュー"
                          >
                            <Eye size={14} />
                          </button>
                          {asset.type === 'audio' && (
                            <button
                              onClick={() => handlePlayAudio(asset.id)}
                              className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-accent-orange"
                              title={playingAudio === asset.id ? '停止' : '再生'}
                            >
                              {playingAudio === asset.id ? <Pause size={14} /> : <Play size={14} />}
                            </button>
                          )}
                          {asset.approvalStatus !== 'approved' && (
                            <button
                              onClick={() => handleApprove(asset.id)}
                              className="p-1 hover:bg-nier-accent-green/20 transition-colors text-nier-accent-green"
                              title="承認"
                            >
                              <Check size={14} />
                            </button>
                          )}
                          {asset.approvalStatus !== 'rejected' && (
                            <button
                              onClick={() => handleReject(asset.id)}
                              className="p-1 hover:bg-nier-accent-red/20 transition-colors text-nier-accent-red"
                              title="却下"
                            >
                              <XCircle size={14} />
                            </button>
                          )}
                          <button
                            className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light hover:text-nier-text-main"
                            title="ダウンロード"
                          >
                            <Download size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Preview Modal */}
      {selectedAsset && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
          <div className="bg-nier-bg-main border border-nier-border-light max-w-4xl max-h-[90vh] w-full overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between px-4 py-3 bg-nier-bg-header border-b border-nier-border-light">
              <div className="flex items-center gap-2">
                {(() => {
                  const Icon = typeIcons[selectedAsset.type]
                  return <Icon size={16} className={typeColors[selectedAsset.type]} />
                })()}
                <span className="text-nier-body font-medium">{selectedAsset.name}</span>
              </div>
              <button
                onClick={() => setSelectedAsset(null)}
                className="p-1 hover:bg-nier-bg-selected transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 overflow-auto max-h-[calc(90vh-60px)]">
              {selectedAsset.type === 'image' && selectedAsset.url && (
                <div className="flex flex-col items-center">
                  <img
                    src={selectedAsset.url}
                    alt={selectedAsset.name}
                    className="max-w-full max-h-[60vh] object-contain"
                  />
                </div>
              )}

              {selectedAsset.type === 'audio' && (
                <div className="flex flex-col items-center py-12">
                  <div className="w-32 h-32 rounded-full bg-nier-bg-header border-4 border-nier-accent-orange flex items-center justify-center mb-6">
                    <Music size={48} className="text-nier-accent-orange" />
                  </div>
                  <div className="text-nier-h2 mb-2">{selectedAsset.name}</div>
                  <div className="text-nier-text-light mb-6">
                    {selectedAsset.duration} | {selectedAsset.size}
                  </div>
                  <button
                    onClick={() => handlePlayAudio(selectedAsset.id)}
                    className="px-8 py-3 bg-nier-accent-orange text-white flex items-center gap-2 hover:opacity-90 transition-opacity"
                  >
                    {playingAudio === selectedAsset.id ? (
                      <>
                        <Pause size={20} />
                        停止
                      </>
                    ) : (
                      <>
                        <Play size={20} />
                        再生
                      </>
                    )}
                  </button>
                </div>
              )}

              {selectedAsset.type === 'document' && (
                <div className="bg-nier-bg-header p-6">
                  <pre className="text-nier-small whitespace-pre-wrap">
                    {`# ${selectedAsset.name}\n\nこのドキュメントのプレビューです。\n実際の実装ではMarkdownレンダリングが行われます。\n\n## セクション1\n\nコンテンツがここに表示されます...`}
                  </pre>
                </div>
              )}

              {selectedAsset.type === 'code' && (
                <div className="bg-nier-bg-header p-6">
                  <pre className="text-nier-small font-mono whitespace-pre-wrap text-nier-accent-green">
                    {`// ${selectedAsset.name}\n\nexport class PlayerController {\n  private velocity: Vector2 = { x: 0, y: 0 };\n  private position: Vector2 = { x: 0, y: 0 };\n\n  update(deltaTime: number): void {\n    // Update player position\n    this.position.x += this.velocity.x * deltaTime;\n    this.position.y += this.velocity.y * deltaTime;\n  }\n}`}
                  </pre>
                </div>
              )}

              {/* Asset Info */}
              <div className="mt-6 pt-6 border-t border-nier-border-light">
                <div className="grid grid-cols-5 gap-4 text-nier-small">
                  <div>
                    <span className="text-nier-text-light block">タイプ</span>
                    <span className={typeColors[selectedAsset.type]}>
                      {typeLabels[selectedAsset.type]}
                    </span>
                  </div>
                  <div>
                    <span className="text-nier-text-light block">状態</span>
                    <span className={cn('px-1.5 py-0.5 border inline-block', approvalBgColors[selectedAsset.approvalStatus])}>
                      {approvalStatusLabels[selectedAsset.approvalStatus]}
                    </span>
                  </div>
                  <div>
                    <span className="text-nier-text-light block">サイズ</span>
                    <span>{selectedAsset.size}</span>
                  </div>
                  <div>
                    <span className="text-nier-text-light block">生成エージェント</span>
                    <span>{selectedAsset.agent}</span>
                  </div>
                  <div>
                    <span className="text-nier-text-light block">作成日時</span>
                    <span>{new Date(selectedAsset.createdAt).toLocaleString('ja-JP')}</span>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="mt-6 flex gap-3">
                {selectedAsset.approvalStatus !== 'approved' && (
                  <Button onClick={() => handleApprove(selectedAsset.id)}>
                    <Check size={14} className="mr-1.5" />
                    承認
                  </Button>
                )}
                {selectedAsset.approvalStatus !== 'rejected' && (
                  <Button
                    variant="secondary"
                    onClick={() => handleReject(selectedAsset.id)}
                    className="border-nier-accent-red text-nier-accent-red hover:bg-nier-accent-red/10"
                  >
                    <XCircle size={14} className="mr-1.5" />
                    却下
                  </Button>
                )}
                {selectedAsset.approvalStatus !== 'pending' && (
                  <Button variant="secondary" onClick={() => handleSetPending(selectedAsset.id)}>
                    未承認に戻す
                  </Button>
                )}
                <Button variant="secondary">
                  <Download size={14} className="mr-1.5" />
                  ダウンロード
                </Button>
                <Button variant="secondary" onClick={() => setSelectedAsset(null)}>
                  閉じる
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
