export interface GlobalCostSettings{
 global_enabled:boolean
 global_monthly_limit:number
 alert_threshold:number
 stop_on_budget_exceeded:boolean
 services:Record<string,ServiceCostSettings>
 updated_at:string|null
}

export interface ServiceCostSettings{
 enabled:boolean
 monthly_limit:number
}

export interface GlobalCostSettingsUpdate{
 global_enabled?:boolean
 global_monthly_limit?:number
 alert_threshold?:number
 stop_on_budget_exceeded?:boolean
 services?:Record<string,ServiceCostSettings>
}

export interface BudgetStatus{
 current_usage:number
 monthly_limit:number
 remaining:number
 usage_percent:number
 alert_threshold:number
 is_over_budget:boolean
 is_warning:boolean
 stop_on_budget_exceeded:boolean
 global_enabled:boolean
}

export interface CostHistoryItem{
 id:string
 project_id:string
 agent_id:string|null
 agent_type:string|null
 service_type:string
 provider_id:string|null
 model_id:string|null
 input_tokens:number
 output_tokens:number
 unit_count:number
 cost_usd:number
 recorded_at:string|null
 metadata:Record<string,unknown>|null
}

export interface CostHistoryResponse{
 items:CostHistoryItem[]
 total:number
 limit:number
 offset:number
}

export interface CostSummaryByService{
 input_tokens:number
 output_tokens:number
 call_count:number
}

export interface CostSummaryByProject{
 call_count:number
}

export interface CostSummary{
 year:number
 month:number
 total_cost:number
 by_service:Record<string,CostSummaryByService>
 by_project:Record<string,CostSummaryByProject>
}
