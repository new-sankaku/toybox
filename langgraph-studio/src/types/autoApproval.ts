export type ContentCategory='code'|'image'|'audio'|'music'|'document'

export interface AutoApprovalRule{
 category:ContentCategory
 enabled:boolean
 label:string
}
