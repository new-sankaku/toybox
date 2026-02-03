import{useMetricsStore}from'@/stores/metricsStore'

interface OutputCategory{
 key:string
 label:string
 defaultUnit:string
}

const OUTPUT_CATEGORIES:OutputCategory[]=[
 {key:'characters',label:'キャラ',defaultUnit:'体'},
 {key:'backgrounds',label:'背景',defaultUnit:'枚'},
 {key:'ui',label:'UI',defaultUnit:'点'},
 {key:'effects',label:'効果',defaultUnit:'種'},
 {key:'music',label:'BGM',defaultUnit:'曲'},
 {key:'sfx',label:'SFX',defaultUnit:'個'},
 {key:'voice',label:'Voice',defaultUnit:'件'},
 {key:'video',label:'動画',defaultUnit:'本'},
 {key:'scenarios',label:'シナリオ',defaultUnit:'本'},
 {key:'code',label:'コード',defaultUnit:'行'},
 {key:'documents',label:'Doc',defaultUnit:'件'}
]

export default function OutputSummaryGrid():JSX.Element{
 const metrics=useMetricsStore(state=>state.projectMetrics)
 const counts=metrics?.generationCounts

 return(
  <div className="nier-card h-full flex flex-col">
   <div className="flex-1 p-2 overflow-auto">
    <div className="grid grid-cols-4 gap-1.5">
     {OUTPUT_CATEGORIES.map(cat=>{
      const data=counts?.[cat.key as keyof import('@/types/project').GenerationCounts]
      const count=data?.count||0
      const unit=data?.unit||cat.defaultUnit
      return(
       <div
        key={cat.key}
        className="nier-surface-main border border-nier-border-light p-1.5 text-center"
       >
        <div className="text-lg font-medium leading-tight">
         {count}
        </div>
        <div className="text-[9px] text-nier-text-light tracking-nier truncate">
         {cat.label}
         <span className="ml-0.5 opacity-70">({unit})</span>
        </div>
       </div>
)
     })}
    </div>
   </div>
  </div>
)
}
