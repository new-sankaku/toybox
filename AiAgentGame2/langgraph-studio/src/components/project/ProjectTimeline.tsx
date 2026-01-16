import { CheckCircle, Circle, Play, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PhaseNumber } from '@/types/project'

interface TimelinePhase {
  phase: PhaseNumber
  name: string
  description: string
  status: 'completed' | 'active' | 'pending'
  progress?: number
  agents?: string[]
}

interface ProjectTimelineProps {
  currentPhase: PhaseNumber
  phases?: TimelinePhase[]
  vertical?: boolean
}

const defaultPhases: TimelinePhase[] = [
  {
    phase: 1,
    name: 'Planning',
    description: 'Concept, Design, Scenario, Characters, World Building',
    status: 'pending',
    agents: ['ConceptAgent', 'DesignAgent', 'ScenarioAgent', 'CharacterAgent', 'WorldAgent']
  },
  {
    phase: 2,
    name: 'Development',
    description: 'Code Generation, Asset Creation',
    status: 'pending',
    agents: ['CodeLeader', 'AssetLeader', 'CodeWorkers', 'AssetWorkers']
  },
  {
    phase: 3,
    name: 'Quality',
    description: 'Integration, Testing, Review',
    status: 'pending',
    agents: ['IntegratorAgent', 'TesterAgent', 'ReviewerAgent']
  }
]

function getPhaseStatus(phase: PhaseNumber, currentPhase: PhaseNumber): 'completed' | 'active' | 'pending' {
  if (phase < currentPhase) return 'completed'
  if (phase === currentPhase) return 'active'
  return 'pending'
}

export function ProjectTimeline({ currentPhase, phases, vertical = false }: ProjectTimelineProps) {
  const timelinePhases = phases || defaultPhases.map((p) => ({
    ...p,
    status: getPhaseStatus(p.phase, currentPhase)
  }))

  if (vertical) {
    return (
      <div className="space-y-0">
        {timelinePhases.map((phase, index) => (
          <div key={phase.phase} className="relative flex gap-4">
            {/* Line */}
            {index < timelinePhases.length - 1 && (
              <div className="absolute left-[15px] top-8 w-0.5 h-full bg-nier-border-dark" />
            )}

            {/* Icon */}
            <div className="relative z-10 flex-shrink-0">
              <PhaseIcon status={phase.status} />
            </div>

            {/* Content */}
            <div className="pb-8 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-nier-small font-medium tracking-nier">
                  PHASE {phase.phase}
                </span>
                <span className="text-nier-h2 tracking-nier-wide">{phase.name}</span>
              </div>
              <p className="text-nier-small text-nier-text-light mb-2">
                {phase.description}
              </p>
              {phase.agents && (
                <div className="flex flex-wrap gap-1">
                  {phase.agents.map((agent) => (
                    <span
                      key={agent}
                      className="text-nier-caption px-2 py-0.5 bg-nier-bg-selected"
                    >
                      {agent}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  }

  // Horizontal layout
  return (
    <div className="flex items-start">
      {timelinePhases.map((phase, index) => (
        <div key={phase.phase} className="flex-1 relative">
          {/* Connector line */}
          {index < timelinePhases.length - 1 && (
            <div
              className={cn(
                'absolute top-4 left-1/2 w-full h-0.5',
                phase.status === 'completed' ? 'bg-nier-accent-green' : 'bg-nier-border-dark'
              )}
            />
          )}

          {/* Phase content */}
          <div className="relative flex flex-col items-center text-center px-2">
            <PhaseIcon status={phase.status} />
            <div className="mt-3">
              <div className="text-nier-caption text-nier-text-light">
                PHASE {phase.phase}
              </div>
              <div className="text-nier-small font-medium tracking-nier">
                {phase.name}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function PhaseIcon({ status }: { status: 'completed' | 'active' | 'pending' }) {
  const baseClasses = 'w-8 h-8 rounded-full flex items-center justify-center'

  if (status === 'completed') {
    return (
      <div className={cn(baseClasses, 'bg-nier-accent-green text-white')}>
        <CheckCircle size={18} />
      </div>
    )
  }

  if (status === 'active') {
    return (
      <div className={cn(baseClasses, 'bg-nier-accent-orange text-white animate-nier-pulse')}>
        <Play size={16} />
      </div>
    )
  }

  return (
    <div className={cn(baseClasses, 'bg-nier-bg-selected text-nier-text-light')}>
      <Clock size={16} />
    </div>
  )
}
