import type{TabId}from'../../App'

interface Tab{
 id:TabId
 label:string
 icon:string
}

const tabs:Tab[]=[
 {id:'project',label:'PROJECT',icon:'◉'},
 {id:'system',label:'DASHBOARD',icon:'⬡'},
 {id:'checkpoints',label:'CHECKPOINTS',icon:'✦'},
 {id:'agents',label:'AGENTS',icon:'⚔'},
 {id:'data',label:'ASSET',icon:'☰'},
 {id:'ai',label:'AI',icon:'✧'},
 {id:'cost',label:'COST',icon:'¤'},
 {id:'logs',label:'LOGS',icon:'◈'},
 {id:'config',label:'CONFIG',icon:'⚙'}
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
