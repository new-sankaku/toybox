import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import{DollarSign,TrendingUp,Calculator,AlertTriangle}from'lucide-react'

interface CostEstimatorProps{
 currentCost:number
 estimatedTotalCost:number
 budgetLimit?:number
 breakdown:{
  inputTokens:number
  outputTokens:number
  inputCost:number
  outputCost:number
 }
 currency?:string
}

export default function CostEstimator({
 currentCost,
 estimatedTotalCost,
 budgetLimit=10,
 breakdown,
 currency='USD'
}:CostEstimatorProps):JSX.Element{
 const budgetUsedPercent=(currentCost/budgetLimit)*100
 const isOverBudget=currentCost>budgetLimit
 const willExceedBudget=estimatedTotalCost>budgetLimit

 const formatCurrency=(amount:number)=>{
  return new Intl.NumberFormat('en-US',{
   style:'currency',
   currency:currency,
   minimumFractionDigits:4,
   maximumFractionDigits:4
  }).format(amount)
 }

 const formatTokens=(tokens:number)=>{
  if(tokens>=1000000){
   return`${(tokens/1000000).toFixed(2)}M`
  }
  if(tokens>=1000){
   return`${(tokens/1000).toFixed(1)}K`
  }
  return tokens.toString()
 }

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>コスト見積もり</DiamondMarker>
   </CardHeader>
   <CardContent className="space-y-6">
    {/* Current Cost */}
    <div className="text-center py-4 bg-nier-bg-main">
     <div className="flex items-center justify-center gap-2 text-nier-small text-nier-text-light mb-2">
      <DollarSign size={16}/>
      <span>現在のコスト</span>
     </div>
     <div className={cn(
      'text-nier-display font-medium tracking-nier',
      isOverBudget?'text-nier-accent-red' : 'text-nier-text-main'
)}>
      {formatCurrency(currentCost)}
     </div>
    </div>

    {/* Budget Progress */}
    <div>
     <div className="flex items-center justify-between mb-2 text-nier-small">
      <span className="text-nier-text-light">予算使用率</span>
      <span className={cn(
       isOverBudget?'text-nier-accent-red' : 'text-nier-text-main'
)}>
       {budgetUsedPercent.toFixed(1)}%
      </span>
     </div>
     <div className="h-2 bg-nier-bg-main overflow-hidden">
      <div
       className={cn(
        'h-full transition-all duration-300',
        budgetUsedPercent>80
         ?'bg-nier-accent-red'
         : budgetUsedPercent>50
          ?'bg-nier-accent-yellow'
          : 'bg-nier-accent-green'
)}
       style={{width:`${Math.min(budgetUsedPercent,100)}%`}}
      />
     </div>
     <div className="flex items-center justify-between mt-1 text-nier-caption text-nier-text-light">
      <span>予算: {formatCurrency(budgetLimit)}</span>
      <span>残り: {formatCurrency(Math.max(0,budgetLimit-currentCost))}</span>
     </div>
    </div>

    {/* Estimated Final */}
    <div className={cn(
     'p-3',
     willExceedBudget?'bg-nier-accent-red/10' : 'bg-nier-bg-main'
)}>
     <div className="flex items-center justify-between">
      <span className="flex items-center gap-2 text-nier-small text-nier-text-light">
       <TrendingUp size={14}/>
       推定最終コスト
      </span>
      <span className={cn(
       'text-nier-body font-medium',
       willExceedBudget?'text-nier-accent-red' : 'text-nier-accent-blue'
)}>
       {formatCurrency(estimatedTotalCost)}
      </span>
     </div>
     {willExceedBudget&&(
      <div className="flex items-center gap-2 mt-2 text-nier-caption text-nier-accent-red">
       <AlertTriangle size={12}/>
       予算を超過する可能性があります
      </div>
)}
    </div>

    {/* Cost Breakdown */}
    <div className="pt-4 border-t border-nier-border-light">
     <div className="flex items-center gap-2 mb-3 text-nier-small text-nier-text-light">
      <Calculator size={14}/>
      内訳
     </div>
     <div className="space-y-2">
      <div className="flex items-center justify-between text-nier-small">
       <span className="text-nier-text-light">
        入力 ({formatTokens(breakdown.inputTokens)} tokens)
       </span>
       <span className="text-nier-text-main">
        {formatCurrency(breakdown.inputCost)}
       </span>
      </div>
      <div className="flex items-center justify-between text-nier-small">
       <span className="text-nier-text-light">
        出力 ({formatTokens(breakdown.outputTokens)} tokens)
       </span>
       <span className="text-nier-text-main">
        {formatCurrency(breakdown.outputCost)}
       </span>
      </div>
     </div>
    </div>

    {/* Pricing Info */}
    <div className="text-nier-caption text-nier-text-light">
     <p>*Claude APIの価格に基づいて計算</p>
     <p>*入力: $0.003/1K tokens,出力: $0.015/1K tokens</p>
    </div>
   </CardContent>
  </Card>
)
}
