import ProjectStatus from './ProjectStatus'
import PhaseProgress from './PhaseProgress'
import MetricsOverview from './MetricsOverview'
import PendingApprovals from './PendingApprovals'
import ActiveAgents from './ActiveAgents'
import TaskList from './TaskList'
import AssetStatus from './AssetStatus'

export default function DashboardView(): JSX.Element {
  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Page Title */}
      <div className="flex items-baseline gap-3 mb-6">
        <h1 className="text-nier-display font-light tracking-nier-wide">
          DASHBOARD
        </h1>
        <span className="text-nier-body text-nier-text-light">
          - プロジェクト概要
        </span>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-2 gap-5">
        {/* Row 1 */}
        <ProjectStatus />
        <PhaseProgress />

        {/* Row 2 */}
        <MetricsOverview />
        <PendingApprovals />

        {/* Row 3 */}
        <TaskList />
        <AssetStatus />
      </div>

      {/* Agents (Full Width) */}
      <div className="mt-5">
        <ActiveAgents />
      </div>
    </div>
  )
}
