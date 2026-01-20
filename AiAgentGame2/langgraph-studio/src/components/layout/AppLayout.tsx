import{ReactNode}from'react'
import HeaderTabs from'./HeaderTabs'
import ConnectionStatus from'./ConnectionStatus'
import ActivitySidebar from'./ActivitySidebar'
import type{TabId}from'../../App'

interface AppLayoutProps{
 children:ReactNode
 activeTab:TabId
 onTabChange:(tab:TabId)=>void
}

export default function AppLayout({
 children,
 activeTab,
 onTabChange
}:AppLayoutProps):JSX.Element{
 return(
  <div className="flex flex-col h-screen bg-nier-bg-main">
   {/*Header with tabs*/}
   <header className="flex items-center bg-nier-bg-header border-b-2 border-[#3D3A33]">
    <HeaderTabs activeTab={activeTab} onTabChange={onTabChange}/>
    <div className="ml-auto px-4">
     <ConnectionStatus/>
    </div>
   </header>

   {/*Main content area with sidebar*/}
   <div className="flex flex-1 overflow-hidden">
    <main className="flex-1 overflow-auto">
     {children}
    </main>
    <ActivitySidebar/>
   </div>
  </div>
)
}
