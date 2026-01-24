export type ContentCategory='code'|'image'|'audio'|'music'|'document'

export interface AutoApprovalRule{
 category:ContentCategory
 enabled:boolean
 label:string
}

export const DEFAULT_AUTO_APPROVAL_RULES:AutoApprovalRule[]=[
 {category:'code',enabled:false,label:'コード'},
 {category:'image',enabled:false,label:'画像'},
 {category:'audio',enabled:false,label:'音声'},
 {category:'music',enabled:false,label:'音楽'},
 {category:'document',enabled:false,label:'ドキュメント'}
]
