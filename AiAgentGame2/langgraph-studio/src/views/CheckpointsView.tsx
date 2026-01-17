import { useState, useEffect } from 'react'
import { CheckpointListView } from '@/components/checkpoints'
import CheckpointReviewView from '@/components/checkpoints/CheckpointReviewView'
import { Card, CardContent } from '@/components/ui/Card'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { checkpointApi, type ApiCheckpoint } from '@/services/apiService'
import type { Checkpoint, CheckpointType } from '@/types/checkpoint'
import { FolderOpen } from 'lucide-react'

// Convert API checkpoint to frontend Checkpoint type
function convertApiCheckpoint(apiCheckpoint: ApiCheckpoint): Checkpoint {
  return {
    id: apiCheckpoint.id,
    projectId: apiCheckpoint.projectId,
    agentId: apiCheckpoint.agentId,
    type: apiCheckpoint.type as CheckpointType,
    title: apiCheckpoint.title,
    description: apiCheckpoint.description || null,
    output: {
      documentType: apiCheckpoint.output?.format || 'markdown',
      // Store the actual content string for display
      content: apiCheckpoint.output?.content
        ? (typeof apiCheckpoint.output.content === 'string'
            ? { text: apiCheckpoint.output.content }
            : apiCheckpoint.output.content as Record<string, unknown>)
        : undefined,
      summary: typeof apiCheckpoint.output?.content === 'string'
        ? apiCheckpoint.output.content
        : undefined,
    },
    status: apiCheckpoint.status,
    feedback: apiCheckpoint.feedback,
    resolvedAt: apiCheckpoint.resolvedAt,
    createdAt: apiCheckpoint.createdAt,
    updatedAt: apiCheckpoint.updatedAt,
  }
}

export default function CheckpointsView(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { tabResetCounter, pendingCheckpointId, clearPendingCheckpoint } = useNavigationStore()
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([])
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null)
  const [loading, setLoading] = useState(false)

  // Reset selection when tab is clicked (even if same tab)
  // But NOT if we're navigating to a specific checkpoint
  useEffect(() => {
    if (!pendingCheckpointId) {
      setSelectedCheckpoint(null)
    }
  }, [tabResetCounter, pendingCheckpointId])

  // Auto-select checkpoint if navigating from dashboard
  useEffect(() => {
    if (pendingCheckpointId && checkpoints.length > 0) {
      const checkpoint = checkpoints.find(cp => cp.id === pendingCheckpointId)
      if (checkpoint) {
        setSelectedCheckpoint(checkpoint)
        clearPendingCheckpoint()
      }
    }
  }, [pendingCheckpointId, checkpoints, clearPendingCheckpoint])

  // Fetch checkpoints from API
  useEffect(() => {
    if (!currentProject) {
      setCheckpoints([])
      return
    }

    const fetchCheckpoints = async () => {
      setLoading(true)
      try {
        const data = await checkpointApi.listByProject(currentProject.id)
        setCheckpoints(data.map(convertApiCheckpoint))
      } catch (error) {
        console.error('Failed to fetch checkpoints:', error)
        setCheckpoints([])
      } finally {
        setLoading(false)
      }
    }

    fetchCheckpoints()
    const interval = setInterval(fetchCheckpoints, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  // Project not selected
  if (!currentProject) {
    return (
      <div className="p-4 animate-nier-fade-in">
        <div className="nier-page-header-row">
          <div className="nier-page-header-left">
            <h1 className="nier-page-title">CHECKPOINTS</h1>
            <span className="nier-page-subtitle">- レビュー待ち</span>
          </div>
          <div className="nier-page-header-right" />
        </div>
        <Card>
          <CardContent>
            <div className="text-center py-12 text-nier-text-light">
              <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
              <p className="text-nier-body">プロジェクトを選択してください</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  const handleSelectCheckpoint = (checkpoint: Checkpoint) => {
    setSelectedCheckpoint(checkpoint)
  }

  // Helper to find and select next pending checkpoint
  const selectNextPending = (updatedCheckpoints: Checkpoint[], currentId: string) => {
    const pendingCheckpoints = updatedCheckpoints.filter(
      cp => cp.status === 'pending' && cp.id !== currentId
    )
    if (pendingCheckpoints.length > 0) {
      // Select the oldest pending checkpoint
      const nextPending = pendingCheckpoints.reduce((oldest, current) =>
        new Date(oldest.createdAt) < new Date(current.createdAt) ? oldest : current
      )
      setSelectedCheckpoint(nextPending)
    } else {
      setSelectedCheckpoint(null)
    }
  }

  const handleApprove = async () => {
    if (!selectedCheckpoint) return
    const currentId = selectedCheckpoint.id
    try {
      await checkpointApi.resolve(selectedCheckpoint.id, 'approved')
      // Refresh checkpoints and select next pending
      const data = await checkpointApi.listByProject(currentProject.id)
      const updatedCheckpoints = data.map(convertApiCheckpoint)
      setCheckpoints(updatedCheckpoints)
      selectNextPending(updatedCheckpoints, currentId)
    } catch (error) {
      console.error('Failed to approve checkpoint:', error)
    }
  }

  const handleReject = async (reason: string) => {
    if (!selectedCheckpoint) return
    const currentId = selectedCheckpoint.id
    try {
      await checkpointApi.resolve(selectedCheckpoint.id, 'rejected', reason)
      // Refresh checkpoints and select next pending
      const data = await checkpointApi.listByProject(currentProject.id)
      const updatedCheckpoints = data.map(convertApiCheckpoint)
      setCheckpoints(updatedCheckpoints)
      selectNextPending(updatedCheckpoints, currentId)
    } catch (error) {
      console.error('Failed to reject checkpoint:', error)
    }
  }

  const handleRequestChanges = async (feedback: string) => {
    if (!selectedCheckpoint) return
    const currentId = selectedCheckpoint.id
    try {
      await checkpointApi.resolve(selectedCheckpoint.id, 'revision_requested', feedback)
      // Refresh checkpoints and select next pending
      const data = await checkpointApi.listByProject(currentProject.id)
      const updatedCheckpoints = data.map(convertApiCheckpoint)
      setCheckpoints(updatedCheckpoints)
      selectNextPending(updatedCheckpoints, currentId)
    } catch (error) {
      console.error('Failed to request changes:', error)
    }
  }

  const handleClose = () => {
    setSelectedCheckpoint(null)
  }

  // Show review view if checkpoint is selected
  if (selectedCheckpoint) {
    return (
      <CheckpointReviewView
        checkpoint={selectedCheckpoint}
        onApprove={handleApprove}
        onReject={handleReject}
        onRequestChanges={handleRequestChanges}
        onClose={handleClose}
      />
    )
  }

  // Show checkpoint list
  return (
    <CheckpointListView
      checkpoints={checkpoints}
      onSelectCheckpoint={handleSelectCheckpoint}
      selectedCheckpointId={undefined}
      loading={loading}
    />
  )
}
