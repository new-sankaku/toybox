import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'
import { Image, Music, FileCode } from 'lucide-react'

type AssetType = 'image' | 'audio' | 'code'

interface AssetCategory {
  type: AssetType
  label: string
  icon: typeof Image
  generated: number
  total: number
}

export default function AssetStatus(): JSX.Element {
  // Mock data
  const categories: AssetCategory[] = [
    { type: 'image', label: '画像', icon: Image, generated: 12, total: 24 },
    { type: 'audio', label: '音声', icon: Music, generated: 3, total: 8 },
    { type: 'code', label: 'コード', icon: FileCode, generated: 45, total: 120 }
  ]

  const totalGenerated = categories.reduce((acc, c) => acc + c.generated, 0)
  const totalAssets = categories.reduce((acc, c) => acc + c.total, 0)

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Assets</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">
          <span className="text-nier-accent-green">{totalGenerated}/{totalAssets}</span>
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        {categories.map((category) => {
          const Icon = category.icon
          const progress = category.total > 0 ? (category.generated / category.total) * 100 : 0
          return (
            <div key={category.type} className="flex items-center gap-3">
              <Icon size={14} className="text-nier-text-light shrink-0" />
              <span className="text-nier-small w-12">{category.label}</span>
              <Progress value={progress} className="flex-1 h-1.5" />
              <span className={cn(
                'text-nier-caption w-14 text-right',
                progress === 100 ? 'text-nier-accent-green' : 'text-nier-text-light'
              )}>
                {category.generated}/{category.total}
              </span>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
