import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{FileText,Download,ChevronLeft,ChevronRight}from'lucide-react'
import{useGlobalCostSettingsStore}from'@/stores/globalCostSettingsStore'
import{costReportApi}from'@/services/apiService'

export function CostReportPanel():JSX.Element{
 const{history,summary,loading,fetchHistory,fetchSummary}=useGlobalCostSettingsStore()
 const now=new Date()
 const[year,setYear]=useState(now.getFullYear())
 const[month,setMonth]=useState(now.getMonth()+1)
 const[page,setPage]=useState(0)
 const pageSize=20

 useEffect(()=>{
  fetchSummary({year,month})
  fetchHistory({year,month,limit:pageSize,offset:page*pageSize})
 },[year,month,page,fetchSummary,fetchHistory])

 const handlePrevMonth=useCallback(()=>{
  if(month===1){
   setYear(y=>y-1)
   setMonth(12)
  }else{
   setMonth(m=>m-1)
  }
  setPage(0)
 },[month])

 const handleNextMonth=useCallback(()=>{
  if(month===12){
   setYear(y=>y+1)
   setMonth(1)
  }else{
   setMonth(m=>m+1)
  }
  setPage(0)
 },[month])

 const handleExportCsv=()=>{
  const url=costReportApi.getExportCsvUrl({year,month})
  window.open(url,'_blank')
 }

 const handleExportJson=()=>{
  const url=costReportApi.getExportJsonUrl({year,month})
  window.open(url,'_blank')
 }

 const formatDate=(dateStr:string|null):string=>{
  if(!dateStr)return'-'
  return new Date(dateStr).toLocaleString('ja-JP',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
 }

 const totalPages=history?Math.ceil(history.total/pageSize):0

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <FileText size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">コスト履歴・レポート</span>
     <div className="ml-auto flex items-center gap-2">
      <Button variant="ghost" size="sm" onClick={handlePrevMonth}>
       <ChevronLeft size={14}/>
      </Button>
      <span className="text-nier-small min-w-[80px] text-center">{year}年{month}月</span>
      <Button variant="ghost" size="sm" onClick={handleNextMonth}>
       <ChevronRight size={14}/>
      </Button>
     </div>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {summary?(
      <div className="space-y-4">
       <div className="grid grid-cols-2 gap-4">
        <div>
         <div className="text-nier-caption text-nier-text-light">合計コスト</div>
         <div className="text-nier-h2 font-mono">${summary.total_cost.toFixed(4)}</div>
        </div>
        <div>
         <div className="text-nier-caption text-nier-text-light">プロジェクト数</div>
         <div className="text-nier-h2 font-mono">{Object.keys(summary.by_project).length}</div>
        </div>
       </div>

       {Object.keys(summary.by_service).length>0&&(
        <div>
         <div className="text-nier-caption text-nier-text-light mb-2">サービス別</div>
         <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {Object.entries(summary.by_service).map(([service,data])=>(
           <div key={service} className="bg-nier-bg-main border border-nier-border-light p-2">
            <div className="text-nier-caption text-nier-text-light">{service}</div>
            <div className="text-nier-small font-mono">{data.call_count}回</div>
           </div>
))}
         </div>
        </div>
)}

       <div className="flex gap-2">
        <Button variant="default" size="sm" onClick={handleExportCsv}>
         <Download size={12}/>
         <span className="ml-1">CSV</span>
        </Button>
        <Button variant="default" size="sm" onClick={handleExportJson}>
         <Download size={12}/>
         <span className="ml-1">JSON</span>
        </Button>
       </div>
      </div>
):(
      <div className="text-center py-4 text-nier-text-light">データなし</div>
)}
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <span className="text-nier-small font-medium">履歴一覧</span>
     {history&&history.total>0&&(
      <span className="text-nier-caption text-nier-text-light ml-2">
       {history.total}件中 {page*pageSize+1}-{Math.min((page+1)*pageSize,history.total)}件
      </span>
)}
    </CardHeader>
    <CardContent className="border-t border-nier-border-light p-0">
     {loading?(
      <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
):history&&history.items.length>0?(
      <>
       <div className="overflow-x-auto">
        <table className="w-full text-nier-small">
         <thead>
          <tr className="border-b border-nier-border-light bg-nier-bg-main">
           <th className="px-3 py-2 text-left text-nier-text-light font-normal">日時</th>
           <th className="px-3 py-2 text-left text-nier-text-light font-normal">サービス</th>
           <th className="px-3 py-2 text-left text-nier-text-light font-normal">モデル</th>
           <th className="px-3 py-2 text-right text-nier-text-light font-normal">トークン</th>
           <th className="px-3 py-2 text-right text-nier-text-light font-normal">コスト</th>
          </tr>
         </thead>
         <tbody>
          {history.items.map(item=>(
           <tr key={item.id} className="border-b border-nier-border-light hover:bg-nier-bg-selected">
            <td className="px-3 py-2 text-nier-text-main">{formatDate(item.recorded_at)}</td>
            <td className="px-3 py-2 text-nier-text-main">{item.service_type}</td>
            <td className="px-3 py-2 text-nier-text-light truncate max-w-[150px]">{item.model_id||'-'}</td>
            <td className="px-3 py-2 text-right font-mono text-nier-text-main">
             {item.input_tokens>0||item.output_tokens>0
              ?`${item.input_tokens.toLocaleString()}/${item.output_tokens.toLocaleString()}`
              :item.unit_count>1?`${item.unit_count}単位`:'-'}
            </td>
            <td className="px-3 py-2 text-right font-mono text-nier-text-main">${item.cost_usd.toFixed(4)}</td>
           </tr>
))}
         </tbody>
        </table>
       </div>
       {totalPages>1&&(
        <div className="flex items-center justify-center gap-2 py-3 border-t border-nier-border-light">
         <Button variant="ghost" size="sm" onClick={()=>setPage(p=>p-1)} disabled={page===0}>
          <ChevronLeft size={14}/>
         </Button>
         <span className="text-nier-caption">{page+1}/{totalPages}</span>
         <Button variant="ghost" size="sm" onClick={()=>setPage(p=>p+1)} disabled={page>=totalPages-1}>
          <ChevronRight size={14}/>
         </Button>
        </div>
)}
      </>
):(
      <div className="text-center py-8 text-nier-text-light">履歴がありません</div>
)}
    </CardContent>
   </Card>
  </div>
)
}
