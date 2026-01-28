import{useState,useEffect,useMemo,useCallback,useRef}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Progress}from'@/components/ui/Progress'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{useCostSettingsStore}from'@/stores/costSettingsStore'
import{agentApi,type ApiAgent}from'@/services/apiService'
import{TIMING}from'@/constants/timing'
import{FolderOpen}from'lucide-react'

function formatTokens(num:number):string{
 if(num>=1000000)return`${(num/1000000).toFixed(1)}m`
 if(num>=1000)return`${(num/1000).toFixed(1)}k`
 return num.toString()
}

function getAgentKey(type:string):string{
 if(type.endsWith('_leader'))return type.replace('_leader','')
 if(type.endsWith('_worker'))return type.replace('_worker','')
 return type
}

export default function CostView():JSX.Element{
 const{currentProject,dataVersion}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const{uiPhases,agentServiceMap,serviceLabels}=useUIConfigStore()
 const{pricing,settings,fetchPricing}=useCostSettingsStore()
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[loading,setLoading]=useState(false)
 const intervalRef=useRef<ReturnType<typeof setInterval>|null>(null)

 useEffect(()=>{
  fetchPricing()
 },[fetchPricing])

 const phaseGroups=useMemo(()=>{
  const groups:Record<string,{label:string;agents:string[]}>={}
  uiPhases.forEach((phase,idx)=>{
   groups[`phase${idx}`]={label:phase.label,agents:phase.agents}
  })
  return groups
 },[uiPhases])

 const fetchData=useCallback(async()=>{
  if(!currentProject)return
  try{
   const agentsData=await agentApi.listByProject(currentProject.id)
   setAgents(agentsData)
  }catch(error){
   console.error('Failed to fetch cost data:',error)
  }
 },[currentProject?.id])

 useEffect(()=>{
  if(!currentProject){
   setAgents([])
   return
  }
  setLoading(true)
  fetchData().finally(()=>setLoading(false))
  intervalRef.current=setInterval(fetchData,TIMING.polling.metrics)
  return()=>{
   if(intervalRef.current)clearInterval(intervalRef.current)
  }
 },[currentProject?.id,fetchData,dataVersion])

 const aiServiceGroups=useMemo(()=>{
  const groups:Record<string,{label:string;agents:string[]}>={}
  Object.entries(agentServiceMap).forEach(([agent,service])=>{
   if(!groups[service]){
    groups[service]={label:serviceLabels[service]||service,agents:[]}
   }
   groups[service].agents.push(agent)
  })
  return groups
 },[agentServiceMap,serviceLabels])

 const calculateCost=useCallback((input:number,output:number):number=>{
  if(!pricing)return 0
  const llmModel=Object.entries(pricing.models).find(
   ([,m])=>m.pricing&&(m.pricing.input!==undefined||m.pricing.output!==undefined)
)
  if(!llmModel)return 0
  const modelPricing=llmModel[1].pricing
  const inputPer1M=modelPricing?.input||0
  const outputPer1M=modelPricing?.output||0
  return(input/1000000)*inputPer1M+(output/1000000)*outputPer1M
 },[pricing])

 const agentTokenMap=useMemo(()=>{
  const map=new Map<string,{input:number;output:number}>()
  agents.forEach(agent=>{
   const key=getAgentKey(agent.type)
   const existing=map.get(key)||{input:0,output:0}
   map.set(key,{
    input:existing.input+(agent.inputTokens||0),
    output:existing.output+(agent.outputTokens||0)
   })
  })
  return map
 },[agents])

 const createGroupedData=(groups:Record<string,{label:string;agents:string[]}>)=>{
  return Object.entries(groups).map(([groupKey,config])=>{
   const agentItems=config.agents.map(agentKey=>{
    const tokens=agentTokenMap.get(agentKey)||{input:0,output:0}
    return{
     key:agentKey,
     name:getLabel(agentKey),
     input:tokens.input,
     output:tokens.output,
     cost:calculateCost(tokens.input,tokens.output)
    }
   }).filter(a=>a.input>0||a.output>0)
   const groupInput=agentItems.reduce((s,a)=>s+a.input,0)
   const groupOutput=agentItems.reduce((s,a)=>s+a.output,0)
   return{
    key:groupKey,
    label:config.label,
    agents:agentItems,
    input:groupInput,
    output:groupOutput,
    cost:calculateCost(groupInput,groupOutput)
   }
  }).filter(g=>g.agents.length>0)
 }

 const serviceGroupedData=useMemo(()=>createGroupedData(aiServiceGroups),[agentTokenMap,getLabel,aiServiceGroups,calculateCost])
 const phaseGroupedData=useMemo(()=>createGroupedData(phaseGroups),[agentTokenMap,getLabel,phaseGroups,calculateCost])

 const totals=useMemo(()=>{
  const input=agents.reduce((sum,a)=>sum+(a.inputTokens||0),0)
  const output=agents.reduce((sum,a)=>sum+(a.outputTokens||0),0)
  return{
   input,
   output,
   cost:calculateCost(input,output)
  }
 },[agents,calculateCost])

 const budgetLimit=settings?.globalMonthlyLimit??0

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
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

 const renderGroupTable=(data:ReturnType<typeof createGroupedData>,title:string)=>(
  <Card className="flex-1 flex flex-col overflow-hidden">
   <CardHeader>
    <DiamondMarker>{title}</DiamondMarker>
   </CardHeader>
   <CardContent className="p-2 flex-1 overflow-y-auto">
    {loading&&data.length===0?(
     <div className="text-nier-text-light text-nier-small">読み込み中...</div>
):data.length===0?(
     <div className="text-nier-text-light text-nier-small">データがありません</div>
):(
     <div>
      <div className="grid grid-cols-[1fr_50px_50px_60px] gap-x-2 text-nier-small py-0.5 border-b border-nier-border-light mb-1 pb-1">
       <span className="font-medium"></span>
       <span className="text-right font-medium">In</span>
       <span className="text-right font-medium">Out</span>
       <span className="text-right font-medium">コスト</span>
      </div>
      {data.map(group=>(
       <div key={group.key}>
        <div className="grid grid-cols-[1fr_50px_50px_60px] gap-x-2 text-nier-small py-0.5 bg-nier-bg-panel">
         <span className="font-medium text-nier-text-main">{group.label}</span>
         <span className="text-right text-nier-text-light">{formatTokens(group.input)}</span>
         <span className="text-right text-nier-text-light">{formatTokens(group.output)}</span>
         <span className="text-right font-medium">${group.cost.toFixed(2)}</span>
        </div>
        {group.agents.map(agent=>(
         <div key={agent.key} className="grid grid-cols-[1fr_50px_50px_60px] gap-x-2 text-nier-small py-0.5 pl-3">
          <span className="text-nier-text-light truncate">{agent.name}</span>
          <span className="text-right text-nier-text-light">{formatTokens(agent.input)}</span>
          <span className="text-right text-nier-text-light">{formatTokens(agent.output)}</span>
          <span className="text-right text-nier-text-light">${agent.cost.toFixed(2)}</span>
         </div>
))}
       </div>
))}
     </div>
)}
   </CardContent>
  </Card>
)

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    {renderGroupTable(serviceGroupedData,'AIサービス別')}
    {renderGroupTable(phaseGroupedData,'Phase別')}
    <Card className="flex-1 flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0">
      <DiamondMarker>サマリー</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2 space-y-3 flex-1 overflow-y-auto">
      <div className="border-b border-nier-border-light pb-2">
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">入力</span>
        <span className="font-medium">{formatTokens(totals.input)}</span>
       </div>
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">出力</span>
        <span className="font-medium">{formatTokens(totals.output)}</span>
       </div>
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">合計コスト</span>
        <span className="font-medium">${totals.cost.toFixed(2)}</span>
       </div>
      </div>
      <div>
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">予算</span>
        <span>${budgetLimit.toFixed(2)}</span>
       </div>
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">残り</span>
        <span>${(budgetLimit-totals.cost).toFixed(2)}</span>
       </div>
       <Progress value={(totals.cost/budgetLimit)*100} className="h-1.5 mt-1"/>
       <div className="text-nier-caption text-nier-text-light text-center mt-0.5">
        {((totals.cost/budgetLimit)*100).toFixed(1)}%使用
       </div>
      </div>
     </CardContent>
    </Card>
   </div>
  </div>
)
}
