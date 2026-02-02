import type{TabId}from'../../App'
import{usePendingCheckpointsCount}from'@/stores/checkpointStore'
import{usePendingAssetsCount}from'@/stores/assetStore'
import{useWaitingResponseCount}from'@/stores/interventionStore'

interface Tab{
 id:TabId
 label:string
 icon:string
 hasBadge?:boolean
}

const tabs:Tab[]=[
 {id:'project',label:'プロジェクト',icon:'◎'},
 {id:'system',label:'ダッシュボード',icon:'⬢'},
 {id:'checkpoints',label:'承認',icon:'✓',hasBadge:true},
 {id:'intervention',label:'連絡',icon:'✉',hasBadge:true},
 {id:'agents',label:'エージェント',icon:'⚙'},
 {id:'data',label:'生成素材',icon:'≡',hasBadge:true},
 {id:'cost',label:'コスト',icon:'},
 {id:'logs',label:'ログ',icon:'≫'},
 {id:'config',label:'プロジェクト設定',icon:'⚙'},
 {id:'global-config',label:'共通設定',icon:'⚙'}
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
 const badgeCounts:Record<string,number>={
  checkpoints:pendingCheckpoints,
  intervention:waitingResponse,
  data:pendingAssets
 }
 return(
  <nav className="flex min-w-0">
   {tabs.map((tab)=>{
    const count=tab.hasBadge?badgeCounts[tab.id]??0:0
    return(
     <button
      key={tab.id}
      className={`nier-tab ${activeTab===tab.id?'active':''}`}
      onClick={()=>onTabChange(tab.id)}
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
},
 {id:__PRESERVED_25__,label:__PRESERVED_26__,icon:__PRESERVED_27__},
 {id:__PRESERVED_28__,label:__PRESERVED_29__,icon:__PRESERVED_30__},
 {id:__PRESERVED_31__,label:__PRESERVED_32__,icon:__PRESERVED_33__}
]

function formatBadgeCount(count:number):string{
 return count>99?__PRESERVED_34__:String(count)
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
 const badgeCounts:Record<string,number>={
  checkpoints:pendingCheckpoints,
  intervention:waitingResponse,
  data:pendingAssets
 }
 return(
  <nav className=__PRESERVED_35__>
   {tabs.map((tab)=>{
    const count=tab.hasBadge?badgeCounts[tab.id]??0:0
    return(
     <button
      key={tab.id}
      className={__PRESERVED_36__}
      onClick={()=>onTabChange(tab.id)}
     >
      <span className=__PRESERVED_37__>{tab.icon}</span>
      <span className={tab.hasBadge?__PRESERVED_38__:undefined}>
       {tab.label}
       {tab.hasBadge&&(
        <span
         className={__PRESERVED_39__}
        >
         {count>0?formatBadgeCount(count):__PRESERVED_40__}
        </span>
)}
      </span>
     </button>
)
   })}
  </nav>
)
}
