export interface BrushupPreset{
 id:string
 label:string
 description:string
 targetPhases:string[]
}

export interface BrushupSuggestImage{
 id:string
 url:string
 prompt:string
}

export interface BrushupConfig{
 presets:string[]
 customInstruction:string
 referenceImageIds:string[]
 suggestedImageIds:string[]
 selectedAgents:string[]
 clearAssets:boolean
}
