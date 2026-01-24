import{useState,useEffect,useMemo,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Progress}from'@/components/ui/Progress'
import{Button}from'@/components/ui/Button'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useCostSettingsStore}from'@/stores/costSettingsStore'
import{agentApi,projectSettingsApi,type ApiAgent}from'@/services/apiService'
import{formatNumber}from'@/lib/utils'
import{FolderOpen}from'lucide-react'

type GroupMode='ai_service'|'phase'

const PHASE_GROUPS:Record<string,{label:string;agents:string[]}>={
 phase0:{label:'企画',agents:['concept']},
 phase1:{label:'分割1',agents:['task_split_1']},
 phase2:{label:'設計',agents:['concept_detail','scenario','world','game_design','tech_spec']},
 phase3:{label:'分割2',agents:['task_split_2']},
 phase4:{label:'アセット',agents:['asset_character','asset_background','asset_ui','asset_effect','asset_bgm','asset_voice','asset_sfx']},
 phase5:{label:'分割3',agents:['task_split_3']},
 phase6:{label:'実装',agents:['code','event','ui_integration','asset_integration']},
 phase7:{label:'分割4',agents:['task_split_4']},
 phase8:{label:'テスト',agents:['unit_test','integration_test']}
}

const SERVICE_LABELS:Record<string,string>={
 llm:'LLM',
 image:'画像',
 music:'音楽',
 audio:'音声'
}

function getAgentKey(type:string):string{
 if(type.endsWith('_leader'))return type.replace('_leader','')
 if(type.endsWith('_worker'))return type.replace('_worker','')
 return type
}

interface BarChartProps{
 data:{label:string;value:number;color?:string}[]
 height?:number
}

function SimpleBarChart({data,height=100}:BarChartProps):JSX.Element{
 const maxValue=Math.max(...data.map(d=>d.value),1)
 return(
  <div className="flex items-end gap-1" style={{height}}>
   {data.map((d,i)=>{
    const barH=Math.max((d.value/maxValue)*(height-20),2)
    return(
     <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
      <div
       className="w-full bg-nier-accent-orange"
       style={{height:barH}}
       title={`${d.label}: ${d.value.toFixed(2)}`}
      />
      <span className="text-nier-caption text-nier-text-light truncate w-full text-center">{d.label}</span>
     </div>
)
   })}
  </div>
)
}

interface PieChartProps{
 data:{label:string;value:number}[]
 size?:number
}

function SimplePieChart({data,size=80}:PieChartProps):JSX.Element{
 const total=data.reduce((s,d)=>s+d.value,0)
 if(total===0)return<div className="text-nier-text-light text-nier-caption">データなし</div>
 let currentAngle=0
 const colors=['#c4a35a','#8b7355','#6b5a4e','#5a4a3e','#4a3a2e','#3a2a1e']
 const paths=data.map((d,i)=>{
  const angle=(d.value/total)*360
  const startAngle=currentAngle
  const endAngle=currentAngle+angle
  currentAngle=endAngle
  const startRad=(startAngle-90)*Math.PI/180
  const endRad=(endAngle-90)*Math.PI/180
  const r=size/2-2
  const cx=size/2
  const cy=size/2
  const x1=cx+r*Math.cos(startRad)
  const y1=cy+r*Math.sin(startRad)
  const x2=cx+r*Math.cos(endRad)
  const y2=cy+r*Math.sin(endRad)
  const largeArc=angle>180?1:0
  return(
   <path
    key={i}
    d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${largeArc},1 ${x2},${y2} Z`}
    fill={colors[i%colors.length]}
   >
    <title>{d.label}: ${d.value.toFixed(2)} ({((d.value/total)*100).toFixed(1)}%)</title>
   </path>
)
 })
 return(
  <svg width={size} height={size}>
   {paths}
  </svg>
)
}

export default function CostView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const{pricing,settings,fetchPricing}=useCostSettingsStore()
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[agentServiceMap,setAgentServiceMap]=useState<Record<string,string>>({})
 const[loading,setLoading]=useState(false)
 const[groupMode,setGroupMode]=useState<GroupMode>('ai_service')

 useEffect(()=>{
  fetchPricing()
  projectSettingsApi.getAgentServiceMap().then(setAgentServiceMap).catch(console.error)
 },[fetchPricing])

 useEffect(()=>{
  if(!currentProject){
   setAgents([])
   return
  }

  const fetchData=async()=>{
   setLoading(true)
   try{
    const agentsData=await agentApi.listByProject(currentProject.id)
    setAgents(agentsData)
   }catch(error){
    console.error('Failed to fetch cost data:',error)
    setAgents([])
   }finally{
    setLoading(false)
   }
  }

  fetchData()
 },[currentProject?.id])

 const aiServiceGroups=useMemo(()=>{
  const groups:Record<string,{label:string;agents:string[]}>={}
  Object.entries(agentServiceMap).forEach(([agent,service])=>{
   if(!groups[service]){
    groups[service]={label:SERVICE_LABELS[service]||service,agents:[]}
   }
   groups[service].agents.push(agent)
  })
  return groups
 },[agentServiceMap])

 const calculateCost=useCallback((input:number,output:number):number=>{
  if(!pricing)return 0
  const defaultModel=Object.keys(pricing.models)[0]
  if(!defaultModel)return 0
  const modelPricing=pricing.models[defaultModel]?.pricing
  const inputPer1K=modelPricing?.input||0
  const outputPer1K=modelPricing?.output||0
  return(input/1000)*inputPer1K+(output/1000)*outputPer1K
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

 const groupedData=useMemo(()=>{
  const groups=groupMode==='ai_service'?aiServiceGroups:PHASE_GROUPS
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
 },[agentTokenMap,groupMode,getLabel,aiServiceGroups,calculateCost])

 const totals=useMemo(()=>{
  const input=agents.reduce((sum,a)=>sum+(a.inputTokens||0),0)
  const output=agents.reduce((sum,a)=>sum+(a.outputTokens||0),0)
  return{
   input,
   output,
   cost:calculateCost(input,output)
  }
 },[agents,calculateCost])

 const budgetLimit=settings.globalMonthlyLimit

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

 const chartData=groupedData.map(g=>({label:g.label,value:g.cost}))

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    <Card className="flex-[2] flex flex-col overflow-hidden">
     <CardHeader>
      <div className="flex items-center justify-between w-full">
       <DiamondMarker>エージェント別</DiamondMarker>
       <div className="flex gap-1">
        <Button
         variant={groupMode==='ai_service'?'primary':'secondary'}
         size="sm"
         onClick={()=>setGroupMode('ai_service')}
        >AIサービス</Button>
        <Button
         variant={groupMode==='phase'?'primary':'secondary'}
         size="sm"
         onClick={()=>setGroupMode('phase')}
        >Phase</Button>
       </div>
      </div>
     </CardHeader>
     <CardContent className="p-2 flex-1 overflow-y-auto">
      {loading&&groupedData.length===0?(
       <div className="text-nier-text-light text-nier-small">読み込み中...</div>
):groupedData.length===0?(
       <div className="text-nier-text-light text-nier-small">データがありません</div>
):(
       <div>
        <div className="grid grid-cols-[1fr_50px_50px_55px] text-nier-small py-0.5 border-b border-nier-border-light mb-1 pb-1">
         <span className="font-medium"></span>
         <span className="text-right font-medium">In</span>
         <span className="text-right font-medium">Out</span>
         <span className="text-right font-medium">コスト</span>
        </div>
        {groupedData.map(group=>(
         <div key={group.key}>
          <div className="grid grid-cols-[1fr_50px_50px_55px] text-nier-small py-0.5 bg-nier-bg-panel">
           <span className="font-medium text-nier-text-main">{group.label}</span>
           <span className="text-right text-nier-text-light">{formatNumber(group.input)}</span>
           <span className="text-right text-nier-text-light">{formatNumber(group.output)}</span>
           <span className="text-right font-medium">${group.cost.toFixed(2)}</span>
          </div>
          {group.agents.map(agent=>(
           <div key={agent.key} className="grid grid-cols-[1fr_50px_50px_55px] text-nier-small py-0.5 pl-3">
            <span className="text-nier-text-light truncate">{agent.name}</span>
            <span className="text-right text-nier-text-light">{formatNumber(agent.input)}</span>
            <span className="text-right text-nier-text-light">{formatNumber(agent.output)}</span>
            <span className="text-right text-nier-text-light">${agent.cost.toFixed(2)}</span>
           </div>
))}
         </div>
))}
        <div className="grid grid-cols-[1fr_50px_50px_55px] text-nier-small py-0.5 border-t border-nier-border-light mt-1 pt-1">
         <span className="font-medium">合計</span>
         <span className="text-right font-medium">{formatNumber(totals.input)}</span>
         <span className="text-right font-medium">{formatNumber(totals.output)}</span>
         <span className="text-right font-medium">${totals.cost.toFixed(2)}</span>
        </div>
       </div>
)}
     </CardContent>
    </Card>

    <Card className="flex-1 flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0">
      <DiamondMarker>サマリー</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2 space-y-3 flex-1 overflow-y-auto">
      <div>
       <div className="text-nier-caption text-nier-text-light mb-1">コスト内訳</div>
       <div className="flex items-center gap-3">
        <SimplePieChart data={chartData} size={70}/>
        <div className="flex-1 space-y-0.5">
         {chartData.slice(0,4).map((d,i)=>(
          <div key={i} className="flex justify-between text-nier-caption">
           <span className="text-nier-text-light">{d.label}</span>
           <span>${d.value.toFixed(2)}</span>
          </div>
))}
         {chartData.length>4&&(
          <div className="text-nier-caption text-nier-text-light">+{chartData.length-4}件</div>
)}
        </div>
       </div>
      </div>
      <div>
       <div className="text-nier-caption text-nier-text-light mb-1">グループ別コスト</div>
       <SimpleBarChart data={chartData} height={60}/>
      </div>
      <div className="border-t border-nier-border-light pt-2">
       <div className="flex justify-between text-nier-small py-0.5">
        <span className="text-nier-text-light">合計コスト</span>
        <span className="font-medium">${totals.cost.toFixed(2)}</span>
       </div>
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
