import { useState } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Button } from '@/components/ui/Button'
import { useProjectStore } from '@/stores/projectStore'
import type { Project, ProjectStatus } from '@/types/project'
import { cn } from '@/lib/utils'
import { Play, Pause, Square, Trash2, Plus, FolderOpen, RotateCcw, AlertTriangle } from 'lucide-react'

type Platform = 'web' | 'desktop' | 'mobile'
type Scope = 'mvp' | 'full'
type LLMProvider = 'claude' | 'gpt4'

interface NewProjectForm {
  name: string
  userIdea: string
  references: string
  platform: Platform
  scope: Scope
  llmProvider: LLMProvider
}

const initialForm: NewProjectForm = {
  name: '',
  userIdea: '',
  references: '',
  platform: 'web',
  scope: 'mvp',
  llmProvider: 'claude'
}

// Mock projects for UI demonstration
const mockProjects: Project[] = [
  {
    id: 'proj-001',
    name: 'NebulaForge',
    description: '星を砕いて、宇宙船を創れ',
    status: 'running',
    currentPhase: 1,
    concept: {
      description: '惑星の残骸から資源を収集し、自分だけの宇宙船を設計・強化しながら、銀河の謎を解き明かすクラフト探索ゲーム',
      platform: 'web',
      scope: 'mvp',
      genre: 'サバイバルクラフト',
      targetAudience: 'ミッドコア'
    },
    createdAt: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
    updatedAt: new Date().toISOString()
  },
  {
    id: 'proj-002',
    name: 'Pixel Dungeon',
    description: 'レトロスタイルローグライク',
    status: 'paused',
    currentPhase: 2,
    concept: {
      description: 'クラシックなダンジョン探索RPG',
      platform: 'web',
      scope: 'mvp',
      genre: 'ローグライク',
      targetAudience: 'コアゲーマー'
    },
    createdAt: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
    updatedAt: new Date(Date.now() - 1000 * 60 * 60 * 12).toISOString()
  }
]

const statusLabels: Record<ProjectStatus, string> = {
  draft: '下書き',
  running: '実行中',
  paused: '一時停止',
  completed: '完了',
  failed: 'エラー'
}

const statusColors: Record<ProjectStatus, string> = {
  draft: 'text-nier-text-light',
  running: 'text-nier-accent-green',
  paused: 'text-nier-accent-orange',
  completed: 'text-nier-accent-blue',
  failed: 'text-nier-accent-red'
}

export default function ProjectView(): JSX.Element {
  const { currentProject, setCurrentProject } = useProjectStore()
  const [projects, setProjects] = useState<Project[]>(mockProjects)
  const [showNewForm, setShowNewForm] = useState(false)
  const [form, setForm] = useState<NewProjectForm>(initialForm)
  const [showInitializeDialog, setShowInitializeDialog] = useState(false)

  const handleCreateProject = () => {
    if (!form.name.trim() || !form.userIdea.trim()) return

    const newProject: Project = {
      id: `proj-${Date.now()}`,
      name: form.name,
      description: form.userIdea.slice(0, 50) + (form.userIdea.length > 50 ? '...' : ''),
      status: 'draft',
      currentPhase: 1,
      concept: {
        description: form.userIdea,
        platform: form.platform,
        scope: form.scope,
        genre: undefined,
        targetAudience: undefined
      },
      config: {
        llmProvider: form.llmProvider
      },
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    }

    setProjects([newProject, ...projects])
    setCurrentProject(newProject)
    setForm(initialForm)
    setShowNewForm(false)
  }

  const handleSelectProject = (project: Project) => {
    setCurrentProject(project)
  }

  const handleDeleteProject = (id: string) => {
    setProjects(projects.filter(p => p.id !== id))
    if (currentProject?.id === id) {
      setCurrentProject(null)
    }
  }

  const handleStartProject = () => {
    if (!currentProject) return
    const updated = { ...currentProject, status: 'running' as ProjectStatus }
    setProjects(projects.map(p => p.id === currentProject.id ? updated : p))
    setCurrentProject(updated)
  }

  const handlePauseProject = () => {
    if (!currentProject) return
    const updated = { ...currentProject, status: 'paused' as ProjectStatus }
    setProjects(projects.map(p => p.id === currentProject.id ? updated : p))
    setCurrentProject(updated)
  }

  const handleStopProject = () => {
    if (!currentProject) return
    const updated = { ...currentProject, status: 'draft' as ProjectStatus }
    setProjects(projects.map(p => p.id === currentProject.id ? updated : p))
    setCurrentProject(updated)
  }

  const handleInitializeProject = () => {
    if (!currentProject) return
    const initialized: Project = {
      ...currentProject,
      status: 'draft' as ProjectStatus,
      currentPhase: 1,
      updatedAt: new Date().toISOString()
    }
    setProjects(projects.map(p => p.id === currentProject.id ? initialized : p))
    setCurrentProject(initialized)
    setShowInitializeDialog(false)
  }

  // Check if project can be initialized (not already in initial state)
  const canInitialize = currentProject && (currentProject.status !== 'draft' || currentProject.currentPhase > 1)

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Page Title */}
      <div className="flex items-baseline gap-3 mb-6">
        <h1 className="text-nier-display font-light tracking-nier-wide">
          PROJECT
        </h1>
        <span className="text-nier-body text-nier-text-light">
          - プロジェクト管理
        </span>
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Left: Project List */}
        <div className="col-span-1 space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between w-full">
                <DiamondMarker>プロジェクト一覧</DiamondMarker>
                <button
                  onClick={() => setShowNewForm(true)}
                  className="p-1.5 hover:bg-nier-bg-selected transition-colors"
                  title="新規作成"
                >
                  <Plus size={16} />
                </button>
              </div>
            </CardHeader>
            <CardContent>
              {projects.length === 0 ? (
                <div className="text-center text-nier-text-light py-8">
                  プロジェクトがありません
                </div>
              ) : (
                <div className="space-y-2">
                  {projects.map((project) => (
                    <div
                      key={project.id}
                      onClick={() => handleSelectProject(project)}
                      className={cn(
                        'p-3 border cursor-pointer transition-colors',
                        currentProject?.id === project.id
                          ? 'border-nier-accent-gold bg-nier-bg-selected'
                          : 'border-nier-border-light hover:bg-nier-bg-hover'
                      )}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="text-nier-small font-medium truncate">
                            {project.name}
                          </div>
                          <div className="text-nier-caption text-nier-text-light truncate mt-0.5">
                            {project.description}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 ml-2">
                          <span className={cn('text-nier-caption', statusColors[project.status])}>
                            {statusLabels[project.status]}
                          </span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDeleteProject(project.id)
                            }}
                            className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-accent-red"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </div>
                      <div className="text-nier-caption text-nier-text-light mt-1">
                        Phase {project.currentPhase}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right: New Project Form or Project Details */}
        <div className="col-span-2">
          {showNewForm ? (
            <Card>
              <CardHeader>
                <DiamondMarker>新規プロジェクト作成</DiamondMarker>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {/* Project Name */}
                  <div>
                    <label className="block text-nier-small text-nier-text-light mb-1">
                      プロジェクト名 <span className="text-nier-accent-red">*</span>
                    </label>
                    <input
                      type="text"
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                      placeholder="例: NebulaForge"
                      className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
                    />
                  </div>

                  {/* User Idea */}
                  <div>
                    <label className="block text-nier-small text-nier-text-light mb-1">
                      ゲームアイデア <span className="text-nier-accent-red">*</span>
                    </label>
                    <textarea
                      value={form.userIdea}
                      onChange={(e) => setForm({ ...form, userIdea: e.target.value })}
                      placeholder="作りたいゲームのアイデアを自由に記述してください。ジャンル、世界観、ゲームプレイなど..."
                      rows={5}
                      className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-none"
                    />
                  </div>

                  {/* References */}
                  <div>
                    <label className="block text-nier-small text-nier-text-light mb-1">
                      参考ゲーム（カンマ区切り）
                    </label>
                    <input
                      type="text"
                      value={form.references}
                      onChange={(e) => setForm({ ...form, references: e.target.value })}
                      placeholder="例: Astroneer, FTL, Hollow Knight"
                      className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
                    />
                  </div>

                  {/* Platform & Scope */}
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-nier-small text-nier-text-light mb-1">
                        プラットフォーム
                      </label>
                      <select
                        value={form.platform}
                        onChange={(e) => setForm({ ...form, platform: e.target.value as Platform })}
                        className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
                      >
                        <option value="web">Web</option>
                        <option value="desktop">Desktop</option>
                        <option value="mobile">Mobile</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-nier-small text-nier-text-light mb-1">
                        スコープ
                      </label>
                      <select
                        value={form.scope}
                        onChange={(e) => setForm({ ...form, scope: e.target.value as Scope })}
                        className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
                      >
                        <option value="mvp">MVP（最小構成）</option>
                        <option value="full">Full（フル機能）</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-nier-small text-nier-text-light mb-1">
                        LLMプロバイダー
                      </label>
                      <select
                        value={form.llmProvider}
                        onChange={(e) => setForm({ ...form, llmProvider: e.target.value as LLMProvider })}
                        className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
                      >
                        <option value="claude">Claude</option>
                        <option value="gpt4">GPT-4</option>
                      </select>
                    </div>
                  </div>

                  {/* Buttons */}
                  <div className="flex gap-3 pt-2">
                    <Button onClick={handleCreateProject} disabled={!form.name.trim() || !form.userIdea.trim()}>
                      作成
                    </Button>
                    <Button variant="secondary" onClick={() => setShowNewForm(false)}>
                      キャンセル
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ) : currentProject ? (
            <div className="space-y-4">
              {/* Project Info */}
              <Card>
                <CardHeader>
                  <DiamondMarker>プロジェクト詳細</DiamondMarker>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    <div>
                      <span className="text-nier-caption text-nier-text-light block">名前</span>
                      <span className="text-nier-h2 font-medium">{currentProject.name}</span>
                    </div>
                    <div>
                      <span className="text-nier-caption text-nier-text-light block">ステータス</span>
                      <span className={cn('text-nier-body', statusColors[currentProject.status])}>
                        {statusLabels[currentProject.status]}
                      </span>
                    </div>
                    <div>
                      <span className="text-nier-caption text-nier-text-light block">現在のフェーズ</span>
                      <span className="text-nier-body">Phase {currentProject.currentPhase}</span>
                    </div>
                    {currentProject.concept && (
                      <>
                        <div>
                          <span className="text-nier-caption text-nier-text-light block">ゲームアイデア</span>
                          <span className="text-nier-body">{currentProject.concept.description}</span>
                        </div>
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <span className="text-nier-caption text-nier-text-light block">プラットフォーム</span>
                            <span className="text-nier-body">{currentProject.concept.platform}</span>
                          </div>
                          <div>
                            <span className="text-nier-caption text-nier-text-light block">スコープ</span>
                            <span className="text-nier-body">{currentProject.concept.scope}</span>
                          </div>
                          {currentProject.concept.genre && (
                            <div>
                              <span className="text-nier-caption text-nier-text-light block">ジャンル</span>
                              <span className="text-nier-body">{currentProject.concept.genre}</span>
                            </div>
                          )}
                        </div>
                      </>
                    )}
                    <div>
                      <span className="text-nier-caption text-nier-text-light block">作成日時</span>
                      <span className="text-nier-body">
                        {new Date(currentProject.createdAt).toLocaleString('ja-JP')}
                      </span>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Controls */}
              <Card>
                <CardHeader>
                  <DiamondMarker>実行コントロール</DiamondMarker>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-3">
                    {currentProject.status !== 'running' && (
                      <Button onClick={handleStartProject}>
                        <Play size={14} className="mr-1.5" />
                        {currentProject.status === 'paused' ? '再開' : '開始'}
                      </Button>
                    )}
                    {currentProject.status === 'running' && (
                      <Button onClick={handlePauseProject}>
                        <Pause size={14} className="mr-1.5" />
                        一時停止
                      </Button>
                    )}
                    {(currentProject.status === 'running' || currentProject.status === 'paused') && (
                      <Button variant="secondary" onClick={handleStopProject}>
                        <Square size={14} className="mr-1.5" />
                        停止
                      </Button>
                    )}
                    {canInitialize && (
                      <Button
                        variant="ghost"
                        onClick={() => setShowInitializeDialog(true)}
                        className="text-nier-accent-orange hover:text-nier-accent-red"
                      >
                        <RotateCcw size={14} className="mr-1.5" />
                        初期化
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : (
            <Card>
              <CardContent>
                <div className="text-center py-12 text-nier-text-light">
                  <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
                  <p className="text-nier-body mb-4">プロジェクトを選択するか、新規作成してください</p>
                  <Button onClick={() => setShowNewForm(true)}>
                    <Plus size={14} className="mr-1.5" />
                    新規プロジェクト作成
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Initialize Confirmation Dialog */}
      {showInitializeDialog && currentProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-96">
            <CardHeader>
              <div className="flex items-center gap-2 text-nier-accent-orange">
                <AlertTriangle size={18} />
                <span>初期化の確認</span>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-nier-body mb-4">
                プロジェクト「{currentProject.name}」を初期化しますか？
              </p>
              <p className="text-nier-small text-nier-accent-red mb-6">
                すべての進捗状況とエージェント出力がリセットされます。この操作は取り消せません。
              </p>
              <div className="flex gap-3 justify-end">
                <Button variant="secondary" onClick={() => setShowInitializeDialog(false)}>
                  キャンセル
                </Button>
                <Button
                  onClick={handleInitializeProject}
                  className="bg-nier-accent-red text-white hover:bg-nier-accent-red/80"
                >
                  初期化する
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
