import ProjectStatus from './ProjectStatus'
import PhaseProgress from './PhaseProgress'
import MetricsOverview from './MetricsOverview'
import PendingApprovals from './PendingApprovals'
import ActiveAgents from './ActiveAgents'
import AssetStatus from './AssetStatus'

export default function DashboardView(): JSX.Element {
  return (
    <div className="p-4 animate-nier-fade-in">
      {/* Page Title */}
      <div className="nier-page-header-row">
        <div className="nier-page-header-left">
          <h1 className="nier-page-title">DASHBOARD</h1>
          <span className="nier-page-subtitle">- プロジェクト概要</span>
        </div>
        <div className="nier-page-header-right" />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-2 gap-3">
        {/* Row 1 */}
        <ProjectStatus />
        <PhaseProgress />

        {/* Row 2 */}
        <MetricsOverview />
        <PendingApprovals />

        {/* Row 3 */}
        <ActiveAgents />
        <AssetStatus />
      </div>
    </div>
  )
}
