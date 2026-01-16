import { Play, Pause, CheckCircle, AlertCircle, FileText } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'
import type { Project, ProjectStatus } from '@/types/project'

interface ProjectCardProps {
  project: Project
  onSelect: (project: Project) => void
  isSelected?: boolean
}

const statusConfig: Record<ProjectStatus, {
  icon: typeof Play
  label: string
  variant: 'red' | 'orange' | 'yellow' | 'green' | 'blue'
}> = {
  draft: { icon: FileText, label: 'Draft', variant: 'blue' },
  running: { icon: Play, label: 'Running', variant: 'orange' },
  paused: { icon: Pause, label: 'Paused', variant: 'yellow' },
  completed: { icon: CheckCircle, label: 'Completed', variant: 'green' },
  failed: { icon: AlertCircle, label: 'Failed', variant: 'red' }
}

const phaseNames = ['Planning', 'Development', 'Quality']

export function ProjectCard({ project, onSelect, isSelected }: ProjectCardProps) {
  const config = statusConfig[project.status]
  const Icon = config.icon
  const progress = project.currentPhase ? ((project.currentPhase - 1) / 3) * 100 : 0

  return (
    <Card
      className={cn(
        'cursor-pointer transition-all duration-nier-fast hover:bg-nier-bg-selected',
        isSelected && 'bg-nier-bg-selected border-nier-text-main'
      )}
      onClick={() => onSelect(project)}
    >
      <CardContent className="py-4">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className={cn(
              'w-1.5 h-8',
              config.variant === 'red' && 'bg-nier-accent-red',
              config.variant === 'orange' && 'bg-nier-accent-orange',
              config.variant === 'yellow' && 'bg-nier-accent-yellow',
              config.variant === 'green' && 'bg-nier-accent-green',
              config.variant === 'blue' && 'bg-nier-accent-blue'
            )} />
            <div>
              <h3 className="text-nier-h2 font-medium tracking-nier">{project.name}</h3>
              {project.description && (
                <p className="text-nier-small text-nier-text-light mt-0.5 line-clamp-1">
                  {project.description}
                </p>
              )}
            </div>
          </div>
          <Badge variant={config.variant}>
            <Icon size={12} className="mr-1" />
            {config.label}
          </Badge>
        </div>

        {/* Progress */}
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-nier-caption text-nier-text-light">
              Phase {project.currentPhase}: {phaseNames[project.currentPhase - 1]}
            </span>
            <span className="text-nier-caption text-nier-text-light">
              {Math.round(progress)}%
            </span>
          </div>
          <Progress value={progress} />
        </div>

        {/* Meta */}
        <div className="flex items-center justify-between text-nier-caption text-nier-text-light">
          <span>
            Created: {new Date(project.createdAt).toLocaleDateString()}
          </span>
          {project.concept?.platform && (
            <span className="uppercase">{project.concept.platform}</span>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
