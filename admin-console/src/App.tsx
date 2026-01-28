import{useState}from'react'
import{useAuthStore}from'@/stores/authStore'
import{LoginPage}from'@/pages/LoginPage'
import{ApiKeyPage}from'@/pages/ApiKeyPage'
import{BackupPage}from'@/pages/BackupPage'
import{ArchivePage}from'@/pages/ArchivePage'
import{SystemStatusPage}from'@/pages/SystemStatusPage'
import{cn}from'@/lib/utils'
import{Key,HardDrive,Archive,Server,LogOut,Shield}from'lucide-react'

type PageId='api-keys'|'backups'|'archives'|'system'

const navItems:{id:PageId;label:string;icon:typeof Key}[]=[
 {id:'api-keys',label:'APIキー管理',icon:Key},
 {id:'backups',label:'バックアップ',icon:HardDrive},
 {id:'archives',label:'アーカイブ',icon:Archive},
 {id:'system',label:'システム情報',icon:Server}
]

export function App(){
 const{isAuthenticated,logout}=useAuthStore()
 const[activePage,setActivePage]=useState<PageId>('api-keys')

 if(!isAuthenticated()){
  return <LoginPage/>
 }

 return(
  <div className="min-h-screen flex flex-col">
   <header className="bg-nier-bg-header text-nier-text-header px-6 py-3 flex items-center gap-3">
    <Shield size={18}/>
    <span className="text-nier-h2 tracking-wider">Admin Console</span>
    <button
     className="ml-auto flex items-center gap-1 text-nier-small hover:opacity-80 transition-opacity"
     onClick={logout}
    >
     <LogOut size={14}/>
     <span>ログアウト</span>
    </button>
   </header>
   <div className="flex-1 flex">
    <nav className="w-48 bg-nier-bg-panel border-r border-nier-border-light flex-shrink-0">
     <div className="py-2">
      {navItems.map(item=>{
       const Icon=item.icon
       return(
        <button
         key={item.id}
         className={cn(
          'w-full px-4 py-3 text-left text-nier-small flex items-center gap-2 transition-colors',
          activePage===item.id
           ?'bg-nier-bg-selected text-nier-text-main'
           :'text-nier-text-light hover:bg-nier-bg-main'
         )}
         onClick={()=>setActivePage(item.id)}
        >
         <Icon size={14}/>
         {item.label}
        </button>
       )
      })}
     </div>
    </nav>
    <main className="flex-1 p-6 overflow-y-auto bg-nier-bg-main">
     {activePage==='api-keys'&&<ApiKeyPage/>}
     {activePage==='backups'&&<BackupPage/>}
     {activePage==='archives'&&<ArchivePage/>}
     {activePage==='system'&&<SystemStatusPage/>}
    </main>
   </div>
  </div>
 )
}
