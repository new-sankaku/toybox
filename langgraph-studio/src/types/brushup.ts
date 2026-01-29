import type{components}from'./api-generated'

export type BrushupImageSchema=components['schemas']['BrushupImageSchema']

export interface BrushupOption{
 id:string
 label:string
}

export interface BrushupAgentOptions{
 options:BrushupOption[]
}

export interface BrushupOptionsConfig{
 agents:Record<string,BrushupAgentOptions>
}

export interface BrushupSuggestImage{
 id:string
 url:string
 prompt:string
}

export interface BrushupConfig{
 agentOptions:Record<string,string[]>
 agentInstructions:Record<string,string>
 customInstruction:string
 referenceImageIds:string[]
 selectedAgents:string[]
 clearAssets:boolean
}
