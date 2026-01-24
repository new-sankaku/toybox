export interface ServiceCostLimit{
 enabled:boolean
 monthlyLimit:number
}

export interface CostSettings{
 globalEnabled:boolean
 globalMonthlyLimit:number
 services:Record<string,ServiceCostLimit>
}

export interface PricingUnit{
 input?:string
 output?:string
 per_image?:string
 per_track?:string
 per_1k_chars?:string
}

export interface ModelPricing{
 input?:number
 output?:number
 per_image?:number
 per_track?:number
 per_1k_chars?:number
}

export interface ModelPricingInfo{
 provider:string
 pricing:ModelPricing
}

export interface PricingConfig{
 currency:string
 units:Record<string,PricingUnit>
 models:Record<string,ModelPricingInfo>
}

export const DEFAULT_COST_SETTINGS:CostSettings={
 globalEnabled:false,
 globalMonthlyLimit:100,
 services:{
  llm:{enabled:false,monthlyLimit:50},
  image:{enabled:false,monthlyLimit:20},
  audio:{enabled:false,monthlyLimit:10},
  music:{enabled:false,monthlyLimit:10}
 }
}
