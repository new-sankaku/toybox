import{useState,useEffect,useMemo}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Progress}from'@/components/ui/Progress'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{metricsApi,agentApi,type ApiAgent,type ApiProjectMetrics}from'@/services/apiService'
import{formatNumber}from'@/lib/utils'
import{FolderOpen}from'lucide-react'

const PRICING={
 inputPer1K:0.003,
 outputPer1K:0.015
}

const GENERATION_TYPE_NAMES:Record<string,string>={
 llm:'LLM（企画・設計）',
 image:'画像生成',
 audio:'音楽・SE生成',
 dialogue:'セリフ・シナリオ',
 video:'動画生成'
}

function getGroupKey(type:string):string{
 if(type.endsWith('_leader'))return type.replace('_leader','')
 if(type.endsWith('_worker'))return type.replace('_worker','')
 return type
}

function calculateCost(input:number,output:number):number{
 return(input/1000)*PRICING.inputPer1K+(output/1000)*PRICING.outputPer1K
}

export default function CostView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[metrics,setMetrics]=useState<ApiProjectMetrics|null>(null)
 const[loading,setLoading]=useState(false)

 useEffect(()=>{
  if(!currentProject){
   setAgents([])
   setMetrics(null)
   return
  }

  const fetchData=async()=>{
   setLoading(true)
   try{
    const[agentsData,metricsData]=await Promise.all([
     agentApi.listByProject(currentProject.id),
     metricsApi.getByProject(currentProject.id)
])
    setAgents(agentsData)
    setMetrics(metricsData)
   }catch(error){
    console.error('Failed to fetch cost data:',error)
    setAgents([])
    setMetrics(null)
   }finally{
    setLoading(false)
   }
  }

  fetchData()
 },[currentProject?.id])

 const agentGroups=useMemo(()=>{
  const groupMap=new Map<string,{input:number;output:number}>()

  agents.forEach(agent=>{
   const groupKey=getGroupKey(agent.type)
   const existing=groupMap.get(groupKey)||{input:0,output:0}
   groupMap.set(groupKey,{
    input:existing.input+(agent.inputTokens||0),
    output:existing.output+(agent.outputTokens||0)
   })
  })

  return Array.from(groupMap.entries()).map(([key,tokens])=>({
   key,
   name:getLabel(key),
   input:tokens.input,
   output:tokens.output,
   cost:calculateCost(tokens.input,tokens.output)
  }))
 },[agents,getLabel])

 const totals=useMemo(()=>{
  const input=agents.reduce((sum,a)=>sum+(a.inputTokens||0),0)
  const output=agents.reduce((sum,a)=>sum+(a.outputTokens||0),0)
  return{
   input,
   output,
   cost:calculateCost(input,output)
  }
 },[agents])

 const budgetLimit=10.0

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <div className="nier-page-header-row">
     <div className="nier-page-header-left">
      <h1 className="nier-page-title">COST</h1>
      <span className="nier-page-subtitle">-コスト管理</span>
     </div>
     <div className="nier-page-header-right"/>
    </div>
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
)
 }

 return(
  <div className="p-4 animate-nier-fade-in">
   {/*Header*/}
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">COST</h1>
     <span className="nier-page-subtitle">-コスト管理</span>
    </div>
    <div className="nier-page-header-right"/>
   </div>

   <div className="grid grid-cols-2 gap-3">
    {/*Left Column-Agent Breakdown*/}
    <Card>
     <CardHeader>
      <DiamondMarker>エージェント別</DiamondMarker>
     </CardHeader>
     <CardContent>
      {loading&&agentGroups.length===0?(
       <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
) : agentGroups.length===0?(
       <div className="text-center py-8 text-nier-text-light">データがありません</div>
) : (
       <table className="w-full">
        <thead className="bg-nier-bg-header text-nier-text-header">
         <tr>
          <th className="px-3 py-2 text-left text-nier-small">グループ</th>
          <th className="px-3 py-2 text-right text-nier-small">In(トークン)</th>
          <th className="px-3 py-2 text-right text-nier-small">Out(トークン)</th>
          <th className="px-3 py-2 text-right text-nier-small">コスト</th>
         </tr>
        </thead>
        <tbody className="divide-y divide-nier-border-light">
         {agentGroups.map(group=>(
          <tr key={group.key} className="hover:bg-nier-bg-panel transition-colors">
           <td className="px-3 py-2 text-nier-small">{group.name}</td>
           <td className="px-3 py-2 text-nier-small text-right">{formatNumber(group.input)}</td>
           <td className="px-3 py-2 text-nier-small text-right">{formatNumber(group.output)}</td>
           <td className="px-3 py-2 text-nier-small text-right">${group.cost.toFixed(4)}</td>
          </tr>
))}
        </tbody>
        <tfoot className="bg-nier-bg-header text-nier-text-header">
         <tr>
          <td className="px-3 py-2 text-nier-small font-medium">合計</td>
          <td className="px-3 py-2 text-nier-small font-medium text-right">{formatNumber(totals.input)}</td>
          <td className="px-3 py-2 text-nier-small font-medium text-right">{formatNumber(totals.output)}</td>
          <td className="px-3 py-2 text-nier-small font-medium text-right">${totals.cost.toFixed(4)}</td>
         </tr>
        </tfoot>
       </table>
)}
     </CardContent>
    </Card>

    {/*Right Column-Summary&Type Breakdown*/}
    <div className="space-y-3">
     {/*Summary*/}
     <Card>
      <CardHeader>
       <DiamondMarker>サマリー</DiamondMarker>
      </CardHeader>
      <CardContent className="space-y-3">
       {/*Tokens*/}
       <div className="space-y-2">
        <div className="flex justify-between text-nier-small">
         <span className="text-nier-text-light">使用トークン (In)</span>
         <span>{formatNumber(totals.input)}</span>
        </div>
        <div className="flex justify-between text-nier-small">
         <span className="text-nier-text-light">使用トークン (Out)</span>
         <span>{formatNumber(totals.output)}</span>
        </div>
       </div>

       {/*Cost*/}
       <div className="pt-3 border-t border-nier-border-light space-y-2">
        <div className="flex justify-between text-nier-small">
         <span className="text-nier-text-light">現在コスト</span>
         <span className="font-medium">${totals.cost.toFixed(4)}</span>
        </div>
        <div className="flex justify-between text-nier-small">
         <span className="text-nier-text-light">予算</span>
         <span>${budgetLimit.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-nier-small font-medium">
         <span>残り予算</span>
         <span className="text-nier-text-main">${(budgetLimit-totals.cost).toFixed(2)}</span>
        </div>
        <Progress value={(totals.cost/budgetLimit)*100} className="h-1.5"/>
       </div>
      </CardContent>
     </Card>

     {/*Generation Type Breakdown*/}
     <Card>
      <CardHeader>
       <DiamondMarker>生成タイプ別</DiamondMarker>
      </CardHeader>
      <CardContent>
       {metrics?.tokensByType&&Object.keys(metrics.tokensByType).length>0?(
        <table className="w-full">
         <thead className="bg-nier-bg-header text-nier-text-header">
          <tr>
           <th className="px-3 py-2 text-left text-nier-small">タイプ</th>
           <th className="px-3 py-2 text-right text-nier-small">In(トークン)</th>
           <th className="px-3 py-2 text-right text-nier-small">Out(トークン)</th>
           <th className="px-3 py-2 text-right text-nier-small">コスト</th>
          </tr>
         </thead>
         <tbody className="divide-y divide-nier-border-light">
          {Object.entries(metrics.tokensByType).map(([key,tokens])=>{
           const cost=calculateCost(tokens.input,tokens.output)
           return(
            <tr key={key}>
             <td className="px-3 py-2 text-nier-small">{GENERATION_TYPE_NAMES[key]||key}</td>
             <td className="px-3 py-2 text-nier-small text-right">{formatNumber(tokens.input)}</td>
             <td className="px-3 py-2 text-nier-small text-right">{formatNumber(tokens.output)}</td>
             <td className="px-3 py-2 text-nier-small text-right">${cost.toFixed(4)}</td>
            </tr>
)
          })}
         </tbody>
        </table>
) : (
        <div className="text-center py-4 text-nier-text-light text-nier-small">データがありません</div>
)}
      </CardContent>
     </Card>
    </div>
   </div>
  </div>
)
}
