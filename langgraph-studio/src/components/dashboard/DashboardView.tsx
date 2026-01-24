import WorkflowDiagram from'./WorkflowDiagram'
import AIFieldSection from'./AIFieldSection'

export default function DashboardView():JSX.Element{
 return(
  <div className="p-4 animate-nier-fade-in h-full overflow-y-auto">
   {/*Workflow Diagram*/}
   <WorkflowDiagram/>

   {/*Agent Workspace with AI Field*/}
   <div className="mt-3">
    <AIFieldSection/>
   </div>
  </div>
)
}
