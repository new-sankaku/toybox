import WorkflowDiagram from'./WorkflowDiagram'
import AgentWorkspace from'./AgentWorkspace'

export default function DashboardView():JSX.Element{
 return(
  <div className="p-4 animate-nier-fade-in">
   {/* Page Title */}
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">DASHBOARD</h1>
     <span className="nier-page-subtitle">-プロジェクト概要</span>
    </div>
    <div className="nier-page-header-right"/>
   </div>

   {/* Workflow Diagram */}
   <WorkflowDiagram/>

   {/* Agent Workspace-Gamification view */}
   <div className="mt-3">
    <AgentWorkspace/>
   </div>
  </div>
)
}
