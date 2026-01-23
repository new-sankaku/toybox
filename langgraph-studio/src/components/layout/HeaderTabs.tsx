import type{TabId}from'../../App'

interface Tab{
 id:TabId
 label:string
 icon:string
}

const tabs:Tab[]=[
 {id:'project',label:'プロジェクト',icon:'◉'},
 {id:'system',label:'ダッシュボード',icon:'⬡'},
 {id:'checkpoints',label:'チェックポイント',icon:'✦'},
 {id:'intervention',label:'連絡',icon:'⊕'},
 {id:'agents',label:'エージェント',icon:'⚔'},
 {id:'ai',label:'AI',icon:'◇'},
 {id:'data',label:'生成素材',icon:'☰'},
 {id:'cost',label:'コスト',icon:'¤'},
 {id:'logs',label:'ログ',icon:'◈'},
 {id:'config',label:'設定',icon:'⚙'}
]

interface HeaderTabsProps{
 activeTab:TabId
 onTabChange:(tab:TabId)=>void
}

export default function HeaderTabs({
 activeTab,
 onTabChange
}:HeaderTabsProps):JSX.Element{
 return(
  <nav className="flex">
   {tabs.map((tab)=>(
    <button
     key={tab.id}
     className={`nier-tab ${activeTab===tab.id?'active' : ''}`}
     onClick={()=>onTabChange(tab.id)}
    >
     <span className="text-xs opacity-80">{tab.icon}</span>
     <span>{tab.label}</span>
    </button>
))}
  </nav>
)
}
