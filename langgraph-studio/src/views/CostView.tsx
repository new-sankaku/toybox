import{useState,useEffect,useMemo,useCallback,useRef}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Progress}from'@/components/ui/Progress'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{useCostSettingsStore}from'@/stores/costSettingsStore'
import{useGlobalCostSettingsStore}from'@/stores/globalCostSettingsStore'
import{agentApi,type ApiAgent,type DailyCostItem}from'@/services/apiService'
import{TIMING}from'@/constants/timing'
import{FolderOpen,TrendingUp,TrendingDown,AlertTriangle}from'lucide-react'

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

function CostBarChart({data,height=120}:{data:DailyCostItem[];height?:number}):JSX.Element{
 if(data.length===0){
  return(
   <div className="flex items-center justify-center text-nier-text-light text-nier-small" style={{height}}>
    データがありません
   </div>
)
 }
 const maxCost=Math.max(...data.map(d=>d.cost),0.01)
 const padding={top:8,right:4,bottom:20,left:4}
 const chartH=height-padding.top-padding.bottom
 return(
  <svg width="100%" height={height} className="overflow-visible">
   <line x1={`${padding.left}px`} y1={padding.top+chartH} x2="100%" y2={padding.top+chartH} stroke="var(--nier-border-light,#c0b8a8)" strokeWidth="1"/>
   {data.map((d,i)=>{
    const barH=maxCost>0?(d.cost/maxCost)*chartH:0
    const barW=100/data.length
    const x=barW*i
    const day=d.date.split('-')[2]||''
    return(
     <g key={d.date}>
      <rect
       x={`${x+barW*0.15}%`}
       y={padding.top+chartH-barH}
       width={`${barW*0.7}%`}
       height={Math.max(barH,0)}
       fill="var(--nier-accent,#8b7355)"
       opacity="0.7"
      />
      <title>{d.date}: ${d.cost.toFixed(4)}</title>
      {data.length<=31&&(
       <text
        x={`${x+barW*0.5}%`}
        y={padding.top+chartH+14}
        textAnchor="middle"
        fill="var(--nier-text-light,#8b8070)"
        fontSize="9"
       >
        {(i%Math.ceil(data.length/10)===0||i===data.length-1)?day:''}
       </text>
)}
     </g>
)
   })}
   <text x={`${padding.left}px`} y={padding.top} fill="var(--nier-text-light,#8b8070)" fontSize="9" dominantBaseline="hanging">
    ${maxCost.toFixed(2)}
   </text>
  </svg>
)
}

function CostLineChart({data,budgetLimit,height=120}:{data:DailyCostItem[];budgetLimit:number;height?:number}):JSX.Element{
 const cumulativeData=useMemo(()=>{
  let running=0
  return data.map(d=>{
   running+=d.cost
   return{...d,cumulative:running}
  })
 },[data])
 if(cumulativeData.length===0){
  return(
   <div className="flex items-center justify-center text-nier-text-light text-nier-small" style={{height}}>
    データがありません
   </div>
)
 }
 const maxVal=Math.max(...cumulativeData.map(d=>d.cumulative),budgetLimit>0?budgetLimit:0,0.01)
 const padding={top:8,right:4,bottom:20,left:4}
 const chartH=height-padding.top-padding.bottom
 const points=cumulativeData.map((d,i)=>{
  const x=(i/(cumulativeData.length-1||1))*100
  const y=padding.top+chartH-(d.cumulative/maxVal)*chartH
  return{x,y,d}
 })
 const linePath=points.map((p,i)=>`${i===0?'M':'L'}${p.x}%,${p.y}`).join(' ')
 const budgetY=budgetLimit>0?padding.top+chartH-(budgetLimit/maxVal)*chartH:-1
 return(
  <svg width="100%" height={height} className="overflow-visible">
   <line x1={`${padding.left}px`} y1={padding.top+chartH} x2="100%" y2={padding.top+chartH} stroke="var(--nier-border-light,#c0b8a8)" strokeWidth="1"/>
   {budgetLimit>0&&budgetY>=padding.top&&(
    <line x1="0%" y1={budgetY} x2="100%" y2={budgetY} stroke="#b45555" strokeWidth="1" strokeDasharray="4,3" opacity="0.8"/>
)}
   <polyline fill="none" stroke="var(--nier-accent,#8b7355)" strokeWidth="1.5" points={points.map(p=>`${p.x}%,${p.y}`).join(' ')}/>
   {points.map((p,i)=>(
    <g key={i}>
     <circle cx={`${p.x}%`} cy={p.y} r="2" fill="var(--nier-accent,#8b7355)"/>
     <title>{p.d.date}: 累計 ${p.d.cumulative.toFixed(4)}</title>
    </g>
))}
   <text x={`${padding.left}px`} y={padding.top} fill="var(--nier-text-light,#8b8070)" fontSize="9" dominantBaseline="hanging">
    ${maxVal.toFixed(2)}
   </text>
   {budgetLimit>0&&budgetY>=padding.top&&(
    <text x="100%" y={budgetY-3} fill="#b45555" fontSize="9" textAnchor="end">
     予算: ${budgetLimit.toFixed(2)}
    </text>
)}
  </svg>
)
}

export default function CostView():JSX.Element{
 const{currentProject,dataVersion}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const{uiPhases,agentServiceMap,serviceLabels}=useUIConfigStore()
 const{pricing,settings,fetchPricing}=useCostSettingsStore()
 const{dailyCost,prediction,fetchDailyCost,fetchPrediction,budgetStatus,fetchBudgetStatus}=useGlobalCostSettingsStore()
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[loading,setLoading]=useState(false)
 const intervalRef=useRef<ReturnType<typeof setInterval>|null>(null)

 useEffect(()=>{
  fetchPricing()
  fetchDailyCost()
  fetchPrediction()
  fetchBudgetStatus()
 },[fetchPricing,fetchDailyCost,fetchPrediction,fetchBudgetStatus])

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
  intervalRef.current=setInterval(()=>{
   fetchData()
   fetchDailyCost()
   fetchPrediction()
   fetchBudgetStatus()
  },TIMING.polling.metrics)
  return()=>{
   if(intervalRef.current)clearInterval(intervalRef.current)
  }
 },[currentProject?.id,fetchData,dataVersion,fetchDailyCost,fetchPrediction,fetchBudgetStatus])

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

 const renderGroupTable=(data:ReturnType<typeof createGroupedData>,title:string)=>{
  const totalInput=data.reduce((s,g)=>s+g.input,0)
  const totalOutput=data.reduce((s,g)=>s+g.output,0)
  const totalCost=calculateCost(totalInput,totalOutput)
  return(
   <Card className="flex-1 flex flex-col overflow-hidden">
    <CardHeader>
     <DiamondMarker>{title}</DiamondMarker>
    </CardHeader>
    <CardContent className="p-2 flex-1 overflow-y-auto flex flex-col">
     {loading&&data.length===0?(
      <div className="text-nier-text-light text-nier-small">読み込み中...</div>
):data.length===0?(
      <div className="text-nier-text-light text-nier-small">データがありません</div>
):(
      <>
       <div>
        <div className="grid grid-cols-[1fr_50px_50px_60px] gap-x-2 text-nier-small py-0.5 border-b border-nier-border-light pb-1">
         <span className="font-medium"></span>
         <span className="text-right font-medium">In</span>
         <span className="text-right font-medium">Out</span>
         <span className="text-right font-medium">コスト</span>
        </div>
        <div className="grid grid-cols-[1fr_50px_50px_60px] gap-x-2 text-nier-small py-1 border-b border-nier-border-dark mb-2">
         <span className="font-medium text-nier-text-main">合計</span>
         <span className="text-right font-medium">{formatTokens(totalInput)}</span>
         <span className="text-right font-medium">{formatTokens(totalOutput)}</span>
         <span className="text-right font-medium">${totalCost.toFixed(2)}</span>
        </div>
       </div>
       <div className="flex-1 overflow-y-auto">
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
      </>
)}
    </CardContent>
   </Card>
)}

 const renderBudgetAlert=()=>{
  if(!budgetStatus)return null
  if(budgetStatus.is_over_budget){
   return(
    <div className="nier-surface-panel border border-red-400/50 p-2 flex items-center gap-2">
     <AlertTriangle size={16} className="text-red-500 flex-shrink-0"/>
     <span className="text-nier-small text-red-500 font-medium">
      予算超過: 使用額 ${budgetStatus.current_usage.toFixed(2)}/予算 ${budgetStatus.monthly_limit.toFixed(2)} ({budgetStatus.usage_percent.toFixed(1)}%)
     </span>
    </div>
)
  }
  if(budgetStatus.is_warning){
   return(
    <div className="nier-surface-panel border border-amber-400/50 p-2 flex items-center gap-2">
     <AlertTriangle size={16} className="text-amber-500 flex-shrink-0"/>
     <span className="text-nier-small text-amber-600 font-medium">
      予算警告: 使用額 ${budgetStatus.current_usage.toFixed(2)}/予算 ${budgetStatus.monthly_limit.toFixed(2)} ({budgetStatus.usage_percent.toFixed(1)}%)
     </span>
    </div>
)
  }
  return null
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden gap-3">
   {renderBudgetAlert()}
   <div className="flex gap-3 flex-shrink-0" style={{minHeight:'160px',maxHeight:'220px'}}>
    <Card className="flex-1 flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0 py-1">
      <DiamondMarker>日別コスト</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2 flex-1 overflow-hidden">
      <CostBarChart data={dailyCost?.daily??[]} height={140}/>
     </CardContent>
    </Card>
    <Card className="flex-1 flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0 py-1">
      <DiamondMarker>累計コスト推移</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2 flex-1 overflow-hidden">
      <CostLineChart data={dailyCost?.daily??[]} budgetLimit={budgetLimit} height={140}/>
     </CardContent>
    </Card>
    <Card className="flex-[0.8] flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0 py-1">
      <DiamondMarker>コスト予測</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2 flex-1 overflow-y-auto">
      {prediction?(
       <div className="space-y-1.5">
        <div className="flex justify-between text-nier-small py-0.5">
         <span className="text-nier-text-light">日平均</span>
         <span className="font-medium">${prediction.daily_average.toFixed(4)}</span>
        </div>
        <div className="flex justify-between text-nier-small py-0.5">
         <span className="text-nier-text-light">月末予測</span>
         <span className={`font-medium ${prediction.will_exceed_budget?'text-red-500':''}`}>
          ${prediction.projected_total.toFixed(2)}
         </span>
        </div>
        <div className="flex justify-between text-nier-small py-0.5">
         <span className="text-nier-text-light">予算対比</span>
         <span className={`font-medium ${prediction.projected_percent>100?'text-red-500':prediction.projected_percent>80?'text-amber-600':''}`}>
          {prediction.projected_percent.toFixed(1)}%
         </span>
        </div>
        <div className="flex justify-between text-nier-small py-0.5">
         <span className="text-nier-text-light">経過/残り</span>
         <span className="font-medium">{prediction.elapsed_days}日/{prediction.remaining_days}日</span>
        </div>
        {prediction.will_exceed_budget?(
         <div className="flex items-center gap-1 mt-1 p-1 border border-red-400/30">
          <TrendingUp size={12} className="text-red-500"/>
          <span className="text-nier-caption text-red-500">月末までに予算超過の見込み</span>
         </div>
):prediction.monthly_limit>0?(
         <div className="flex items-center gap-1 mt-1 p-1 border border-nier-border-light">
          <TrendingDown size={12} className="text-green-600"/>
          <span className="text-nier-caption text-green-600">予算内の見込み</span>
         </div>
):null}
        {prediction.days_until_limit>0&&prediction.monthly_limit>0&&(
         <div className="text-nier-caption text-nier-text-light text-center mt-1">
          現Paceで残り約{prediction.days_until_limit.toFixed(0)}日で予算到達
         </div>
)}
       </div>
):(
       <div className="text-nier-text-light text-nier-small">読み込み中...</div>
)}
     </CardContent>
    </Card>
   </div>
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
       <Progress value={budgetLimit>0?(totals.cost/budgetLimit)*100:0} className="h-1.5 mt-1"/>
       <div className="text-nier-caption text-nier-text-light text-center mt-0.5">
        {budgetLimit>0?`${((totals.cost/budgetLimit)*100).toFixed(1)}%使用`:'予算未設定'}
       </div>
      </div>
     </CardContent>
    </Card>
   </div>
  </div>
)
}
