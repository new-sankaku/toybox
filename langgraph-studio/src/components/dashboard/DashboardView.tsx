import WorkflowDiagram from'./WorkflowDiagram'
import ApiMonitorTable from'./ApiMonitorTable'
import OutputSummaryGrid from'./OutputSummaryGrid'

export default function DashboardView():JSX.Element{
 return(
  <div className="p-4 animate-nier-fade-in h-full overflow-y-auto">
   <WorkflowDiagram/>
   <div className="mt-3 flex gap-3" style={{height:'40vh',minHeight:'200px',maxHeight:'50vh'}}>
    <div className="flex-[6]">
     <ApiMonitorTable/>
    </div>
    <div className="flex-[4]">
     <OutputSummaryGrid/>
    </div>
   </div>
  </div>
)
}
