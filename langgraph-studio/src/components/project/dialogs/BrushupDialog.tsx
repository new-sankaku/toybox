import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{BrushupReferenceImages}from'@/components/brushup'
import{useBrushupStore}from'@/stores/brushupStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{cn}from'@/lib/utils'
import{RefreshCw,X,Check,Loader2}from'lucide-react'

interface BrushupPhase{
 id:string
 label:string
 agents:string[]
}

interface BrushupDialogProps{
 phases:BrushupPhase[]
 selectedAgents:Set<string>
 clearAssets:boolean
 isLoading:boolean
 onToggleAgent:(agentType:string)=>void
 onTogglePhase:(agents:string[])=>void
 onToggleClearAssets:()=>void
 onSubmit:()=>void
 onClose:()=>void
}

export function BrushupDialog({
 phases,
 selectedAgents,
 clearAssets,
 isLoading,
 onToggleAgent,
 onTogglePhase,
 onToggleClearAssets,
 onSubmit,
 onClose
}:BrushupDialogProps){
 const brushupStore=useBrushupStore()
 const{getLabel:getAgentLabel}=useAgentDefinitionStore()

 return(
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
   <Card className="w-[70vw] max-h-[90vh] flex flex-col">
    <CardHeader>
     <div className="flex items-center justify-between w-full">
      <div className="flex items-center gap-2">
       <RefreshCw size={18}/>
       <span>ブラッシュアップ設定</span>
      </div>
      <button
       type="button"
       onClick={onClose}
       className="p-1 hover:bg-black/20 transition-colors"
      >
       <X size={16}/>
      </button>
     </div>
    </CardHeader>
    <CardContent className="flex-1 overflow-y-auto">
     <div className="space-y-6">
      <div>
       <h3 className="text-nier-body font-medium mb-3">ブラッシュアップ対象エージェント</h3>
       <p className="text-nier-small text-nier-text-light mb-3">
        エージェントを選択し、改善項目を指定してください。
       </p>
       <div className="space-y-3">
        {phases.map(phase=>{
         const phaseSelected=phase.agents.filter(a=>selectedAgents.has(a)).length
         const allSelected=phaseSelected===phase.agents.length
         return(
          <div key={phase.id} className="border border-nier-border-light p-3">
           <button
            type="button"
            onClick={()=>onTogglePhase(phase.agents)}
            className="flex items-center gap-2 w-full text-left mb-2"
           >
            <span className={cn('w-4 h-4 border flex items-center justify-center',
             allSelected?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
            )}>
             {allSelected&&<Check size={12}/>}
             {phaseSelected>0&&!allSelected&&<span className="w-2 h-2 bg-nier-text-light"/>}
            </span>
            <span className="text-nier-body font-medium">{phase.label}</span>
            <span className="text-nier-caption text-nier-text-light ml-auto">
             {phaseSelected}/{phase.agents.length}
            </span>
           </button>
           <div className="space-y-3 pl-6">
            {phase.agents.map(agentType=>{
             const agentInstruction=brushupStore.agentInstructions[agentType]||''
             const isSelected=selectedAgents.has(agentType)
             return(
              <div key={agentType} className="border-b border-nier-border-light pb-3 last:border-b-0 last:pb-0">
               <button
                type="button"
                onClick={()=>onToggleAgent(agentType)}
                className="flex items-center gap-2 py-1"
               >
                <span className={cn('w-3 h-3 border flex items-center justify-center flex-shrink-0',
                 isSelected?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
                )}>
                 {isSelected&&<Check size={10}/>}
                </span>
                <span className="text-nier-small font-medium">{getAgentLabel(agentType)}</span>
               </button>
               {isSelected&&(
                <div className="mt-2 pl-5">
                 <textarea
                  value={agentInstruction}
                  onChange={(e)=>brushupStore.setAgentInstruction(agentType,e.target.value)}
                  placeholder="改善指示を入力..."
                  rows={1}
                  className="w-full px-2 py-1 bg-nier-bg-main border border-nier-border-light text-nier-small focus:border-nier-accent-gold focus:outline-none resize-none overflow-hidden"
                  style={{minHeight:'28px',maxHeight:'112px'}}
                  onInput={(e)=>{
                   const target=e.target as HTMLTextAreaElement
                   target.style.height='auto'
                   target.style.height=Math.min(target.scrollHeight,112)+'px'
                  }}
                 />
                </div>
               )}
              </div>
             )
            })}
           </div>
          </div>
         )
        })}
       </div>
       <div className="mt-3">
        <button
         type="button"
         onClick={onToggleClearAssets}
         className="flex items-center gap-2"
        >
         <span className={cn('w-4 h-4 border flex items-center justify-center',
          clearAssets?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
         )}>
          {clearAssets&&<Check size={12}/>}
         </span>
         <span className="text-nier-small">選択したエージェントが生成したアセットも削除する</span>
        </button>
       </div>
      </div>

      <div className="border-t border-nier-border-light pt-4">
       <h3 className="text-nier-body font-medium mb-3">参考画像</h3>
       <BrushupReferenceImages/>
      </div>

      <div className="border-t border-nier-border-light pt-4">
       <h3 className="text-nier-body font-medium mb-3">全体への追加指示（任意）</h3>
       <textarea
        value={brushupStore.customInstruction}
        onChange={(e)=>brushupStore.setCustomInstruction(e.target.value)}
        placeholder="全エージェントに共通する追加指示があれば記述してください..."
        rows={3}
        className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-y min-h-[84px] max-h-[196px]"
       />
      </div>
     </div>
    </CardContent>
    <div className="flex-shrink-0 flex gap-3 justify-end p-4 border-t border-nier-border-light bg-nier-bg-panel">
     <Button variant="secondary" onClick={onClose}>
      キャンセル
     </Button>
     <Button
      onClick={onSubmit}
      disabled={isLoading||selectedAgents.size===0}
     >
      {isLoading&&<Loader2 size={14} className="mr-1.5 animate-spin"/>}
      ブラッシュアップ開始
     </Button>
    </div>
   </Card>
  </div>
 )
}
