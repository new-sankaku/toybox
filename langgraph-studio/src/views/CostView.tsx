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

interface GenCounts{count:number;unit:string;calls:number}

function getGenerationForAgent(
 agentKey:string,
 counts?:Record<string,GenCounts>
):{calls:string;amount:string}{
 if(!counts)return{calls:'-',amount:'-'}
 const imageAgents=['asset_character','asset_background','asset_ui','asset_effect']
 const musicAgents=['asset_bgm']
 const sfxAgents=['asset_sfx']
 const voiceAgents=['asset_voice']
 const codeAgents=['code','event','ui_integration','asset_integration']
 const docAgents=['concept','concept_detail','game_design','tech_spec','world']
 const scenarioAgents=['scenario']

 let data:GenCounts|undefined
 if(imageAgents.includes(agentKey))data=counts.images
 else if(musicAgents.includes(agentKey))data=counts.music
 else if(sfxAgents.includes(agentKey))data=counts.sfx
 else if(voiceAgents.includes(agentKey))data=counts.voice
 else if(codeAgents.includes(agentKey))data=counts.code
 else if(docAgents.includes(agentKey))data=counts.documents
 else if(scenarioAgents.includes(agentKey))data=counts.scenarios

 if(!data)return{calls:'-',amount:'-'}
 return{
  calls:data.calls>0?`${data.calls}回`:'-',
  amount:data.count>0?`${data.count}${data.unit}`:'-'
 }
}

function getGenerationForType(
 typeKey:string,
 counts?:Record<string,GenCounts>
):{calls:string;amount:string}{
 if(!counts)return{calls:'-',amount:'-'}
 switch(typeKey){
  case'llm':{
   const docs=counts.documents
   const code=counts.code
   const totalCalls=(docs?.calls||0)+(code?.calls||0)
   const parts:string[]=[]
   if(docs&&docs.count>0)parts.push(`${docs.count}件`)
   if(code&&code.count>0)parts.push(`${code.count}行`)
   return{
    calls:totalCalls>0?`${totalCalls}回`:'-',
    amount:parts.length>0?parts.join('/'):'-'
   }
  }
  case'image':{
   const d=counts.images
   return{
    calls:d&&d.calls>0?`${d.calls}回`:'-',
    amount:d&&d.count>0?`${d.count}枚`:'-'
   }
  }
  case'audio':{
   const music=counts.music
   const sfx=counts.sfx
   const voice=counts.voice
   const totalCalls=(music?.calls||0)+(sfx?.calls||0)+(voice?.calls||0)
   const parts:string[]=[]
   if(music&&music.count>0)parts.push(`${music.count}曲`)
   if(sfx&&sfx.count>0)parts.push(`${sfx.count}個`)
   if(voice&&voice.count>0)parts.push(`${voice.count}件`)
   return{
    calls:totalCalls>0?`${totalCalls}回`:'-',
    amount:parts.length>0?parts.join('/'):'-'
   }
  }
  case'dialogue':{
   const d=counts.scenarios
   return{
    calls:d&&d.calls>0?`${d.calls}回`:'-',
    amount:d&&d.count>0?`${d.count}本`:'-'
   }
  }
  default:
   return{calls:'-',amount:'-'}
 }
}

function getTotalGeneration(
 counts?:Record<string,GenCounts>
):{calls:string;amount:string}{
 if(!counts)return{calls:'-',amount:'-'}
 const totalCalls=Object.values(counts).reduce((sum,c)=>sum+(c.calls||0),0)
 const totalAmount=Object.values(counts).reduce((sum,c)=>sum+c.count,0)
 return{
  calls:totalCalls>0?`${totalCalls}回`:'-',
  amount:totalAmount>0?`${totalAmount}件`:'-'
 }
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
   <div className="flex gap-3">
    {/*Agent Breakdown*/}
    <Card className="flex-1">
     <CardHeader>
      <DiamondMarker>エージェント別</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2">
      {loading&&agentGroups.length===0?(
       <div className="text-nier-text-light text-nier-small">読み込み中...</div>
) : agentGroups.length===0?(
       <div className="text-nier-text-light text-nier-small">データがありません</div>
) : (
       <div>
        <div className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5 border-b border-nier-border-light mb-1 pb-1">
         <span className="font-medium"></span>
         <span className="text-right font-medium">回数</span>
         <span className="text-right font-medium">生成量</span>
         <span className="text-right font-medium">In</span>
         <span className="text-right font-medium">Out</span>
         <span className="text-right font-medium">コスト</span>
        </div>
        {agentGroups.map(group=>{
         const gen=getGenerationForAgent(group.key,metrics?.generationCounts)
         return(
          <div key={group.key} className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5">
           <span className="text-nier-text-light truncate">{group.name}</span>
           <span className="text-right text-nier-text-light">{gen.calls}</span>
           <span className="text-right text-nier-text-light">{gen.amount}</span>
           <span className="text-right text-nier-text-light">{formatNumber(group.input)}</span>
           <span className="text-right text-nier-text-light">{formatNumber(group.output)}</span>
           <span className="text-right">${group.cost.toFixed(2)}</span>
          </div>
         )
        })}
        {(()=>{
         const total=getTotalGeneration(metrics?.generationCounts)
         return(
          <div className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5 border-t border-nier-border-light mt-1 pt-1">
           <span className="font-medium">合計</span>
           <span className="text-right font-medium">{total.calls}</span>
           <span className="text-right font-medium">{total.amount}</span>
           <span className="text-right font-medium">{formatNumber(totals.input)}</span>
           <span className="text-right font-medium">{formatNumber(totals.output)}</span>
           <span className="text-right font-medium">${totals.cost.toFixed(2)}</span>
          </div>
         )
        })()}
       </div>
)}
     </CardContent>
    </Card>

    {/*Generation Type*/}
    <Card className="flex-1">
     <CardHeader>
      <DiamondMarker>生成タイプ別</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2">
      {metrics?.tokensByType&&Object.keys(metrics.tokensByType).length>0?(
       <div>
        <div className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5 border-b border-nier-border-light mb-1 pb-1">
         <span className="font-medium"></span>
         <span className="text-right font-medium">回数</span>
         <span className="text-right font-medium">生成量</span>
         <span className="text-right font-medium">In</span>
         <span className="text-right font-medium">Out</span>
         <span className="text-right font-medium">コスト</span>
        </div>
        {Object.entries(metrics.tokensByType).map(([key,tokens])=>{
         const cost=calculateCost(tokens.input,tokens.output)
         const gen=getGenerationForType(key,metrics.generationCounts)
         return(
          <div key={key} className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5">
           <span className="text-nier-text-light truncate">{GENERATION_TYPE_NAMES[key]||key}</span>
           <span className="text-right text-nier-text-light">{gen.calls}</span>
           <span className="text-right text-nier-text-light">{gen.amount}</span>
           <span className="text-right text-nier-text-light">{formatNumber(tokens.input)}</span>
           <span className="text-right text-nier-text-light">{formatNumber(tokens.output)}</span>
           <span className="text-right">${cost.toFixed(2)}</span>
          </div>
)
        })}
       </div>
) : (
       <div className="text-nier-text-light text-nier-small">データがありません</div>
)}
     </CardContent>
    </Card>

    {/*Summary*/}
    <Card className="flex-1">
     <CardHeader>
      <DiamondMarker>サマリー</DiamondMarker>
     </CardHeader>
     <CardContent className="p-2">
      {(()=>{
       const total=getTotalGeneration(metrics?.generationCounts)
       return(
        <>
         <div className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5 border-b border-nier-border-light mb-1 pb-1">
          <span className="font-medium"></span>
          <span className="text-right font-medium">回数</span>
          <span className="text-right font-medium">生成量</span>
          <span className="text-right font-medium">In</span>
          <span className="text-right font-medium">Out</span>
          <span className="text-right font-medium">コスト</span>
         </div>
         <div className="grid grid-cols-[1fr_45px_55px_45px_45px_55px] text-nier-small py-0.5">
          <span className="text-nier-text-light">合計</span>
          <span className="text-right text-nier-text-light">{total.calls}</span>
          <span className="text-right text-nier-text-light">{total.amount}</span>
          <span className="text-right text-nier-text-light">{formatNumber(totals.input)}</span>
          <span className="text-right text-nier-text-light">{formatNumber(totals.output)}</span>
          <span className="text-right">${totals.cost.toFixed(2)}</span>
         </div>
        </>
       )
      })()}
      <div className="flex justify-between text-nier-small py-0.5 border-t border-nier-border-light mt-1 pt-1">
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
     </CardContent>
    </Card>
   </div>
  </div>
)
}
