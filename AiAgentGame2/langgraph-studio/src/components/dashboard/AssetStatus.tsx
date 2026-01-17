import { useState, useEffect, useMemo } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { useProjectStore } from '@/stores/projectStore'
import { assetApi, type ApiAsset } from '@/services/apiService'
import { Image, Music, FileCode, FileText } from 'lucide-react'

type AssetType = 'image' | 'audio' | 'code' | 'document'

interface UnapprovedCategory {
  type: AssetType
  label: string
  icon: typeof Image
  count: number
}

export default function AssetStatus(): JSX.Element {
  const { currentProject } = useProjectStore()
  const [assets, setAssets] = useState<ApiAsset[]>([])

  useEffect(() => {
    if (!currentProject) {
      setAssets([])
      return
    }

    const fetchAssets = async () => {
      try {
        const data = await assetApi.listByProject(currentProject.id)
        setAssets(data)
      } catch (error) {
        console.error('Failed to fetch assets:', error)
        setAssets([])
      }
    }

    fetchAssets()
    const interval = setInterval(fetchAssets, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  // Only unapproved assets
  const unapprovedAssets = useMemo(() =>
    assets.filter(a => a.approvalStatus !== 'approved'),
    [assets]
  )

  const categories = useMemo<UnapprovedCategory[]>(() => {
    const result: UnapprovedCategory[] = []
    const imageCount = unapprovedAssets.filter(a => a.type === 'image').length
    const audioCount = unapprovedAssets.filter(a => a.type === 'audio').length
    const docCount = unapprovedAssets.filter(a => a.type === 'document').length
    const codeCount = unapprovedAssets.filter(a => a.type === 'code').length

    if (imageCount > 0) result.push({ type: 'image', label: '画像', icon: Image, count: imageCount })
    if (audioCount > 0) result.push({ type: 'audio', label: '音声', icon: Music, count: audioCount })
    if (docCount > 0) result.push({ type: 'document', label: 'ドキュメント', icon: FileText, count: docCount })
    if (codeCount > 0) result.push({ type: 'code', label: 'コード', icon: FileCode, count: codeCount })

    return result
  }, [unapprovedAssets])

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>Assets</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Assets ({unapprovedAssets.length})</DiamondMarker>
      </CardHeader>
      <CardContent className="overflow-hidden">
        {unapprovedAssets.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            未承認なし
          </div>
        ) : (
          <div className="space-y-1">
            {categories.map((category) => {
              const Icon = category.icon
              return (
                <div key={category.type} className="flex items-center gap-2">
                  <Icon size={14} className="text-nier-text-light shrink-0" />
                  <span className="text-nier-small flex-1">{category.label}</span>
                  <span className="text-nier-caption text-nier-text-light">未承認</span>
                  <span className="text-nier-caption text-nier-accent-yellow w-12 text-right">
                    {category.count}件
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
