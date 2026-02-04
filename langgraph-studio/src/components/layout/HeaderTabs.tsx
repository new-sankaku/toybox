import type{TabId}from'../../App'
import{usePendingCheckpointsCount}from'@/stores/checkpointStore'
import{usePendingAssetsCount}from'@/stores/assetStore'
import{useWaitingResponseCount}from'@/stores/interventionStore'
import{useProjectStore}from'@/stores/projectStore'

interface Tab{
 id:TabId
 label:string
 icon:string
 hasBadge?:boolean
 alwaysEnabled?:boolean
}

const tabs:Tab[]=[
 {id:'project',label:'プロジェクト',icon:'◎',alwaysEnabled:true},
 {id:'system',label:'ダッシュボード',icon:'⬢'},
 {id:'checkpoints',label:'承認',icon:'✓',hasBadge:true},
 {id:'intervention',label:'連絡',icon:'✉',hasBadge:true},
 {id:'agents',label:'エージェント',icon:'⚙'},
 {id:'data',label:'生成素材',icon:'≡',hasBadge:true},
 {id:'cost',label:'コスト',icon:'¥'},
 {id:'logs',label:'ログ',icon:'≫'},
 {id:'config',label:'プロジェクト設定',icon:'⚙'},
 {id:'global-config',label:'共通設定',icon:'⚙',alwaysEnabled:true}
]

function formatBadgeCount(count:number):string{
 return count>99?'99+':String(count)
}

interface HeaderTabsProps{
 activeTab:TabId
 onTabChange:(tab:TabId)=>void
}

export default function HeaderTabs({
 activeTab,
 onTabChange
}:HeaderTabsProps):JSX.Element{
 const pendingCheckpoints=usePendingCheckpointsCount()
 const pendingAssets=usePendingAssetsCount()
 const waitingResponse=useWaitingResponseCount()
 const currentProject=useProjectStore(s=>s.currentProject)
 const hasProject=!!currentProject
 const badgeCounts:Record<string,number>={
  checkpoints:pendingCheckpoints,
  intervention:waitingResponse,
  data:pendingAssets
 }
 return(
  <nav className="flex min-w-0">
   {tabs.map((tab)=>{
    const count=tab.hasBadge?badgeCounts[tab.id]??0:0
    const disabled=!hasProject&&!tab.alwaysEnabled
    return(
     <button
      key={tab.id}
      className={`nier-tab ${activeTab===tab.id?'active':''} ${disabled?'nier-tab-disabled':''}`}
      onClick={()=>{if(!disabled)onTabChange(tab.id)}}
      disabled={disabled}
     >
      <span className="text-xs opacity-80">{tab.icon}</span>
      <span className={tab.hasBadge?'relative pr-2':undefined}>
       {tab.label}
       {tab.hasBadge&&(
        <span
         className={`absolute -top-2 -right-2 inline-flex items-center justify-center min-w-[1.4em] h-[1.4em] px-[0.3em] text-[10px] font-bold leading-none rounded-full ${count>0?'bg-nier-accent-orange text-white':'invisible'}`}
        >
         {count>0?formatBadgeCount(count):'0'}
        </span>
)}
      </span>
     </button>
)
   })}
  </nav>
)
}
