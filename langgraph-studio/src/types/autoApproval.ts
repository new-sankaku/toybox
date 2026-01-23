export type ContentCategory='code'|'image'|'audio'|'music'|'document'|'system'
export type ActionType='create'|'edit'|'delete'

export interface AutoApprovalRule{
 category:ContentCategory
 action:ActionType
 enabled:boolean
 label:string
}

export interface AutoApprovalSettings{
 rules:Record<string,AutoApprovalRule>
}

export const DEFAULT_AUTO_APPROVAL_RULES:AutoApprovalRule[]=[
 {category:'code',action:'create',enabled:true,label:'生成'},
 {category:'code',action:'edit',enabled:true,label:'修正'},
 {category:'code',action:'delete',enabled:false,label:'削除'},
 {category:'image',action:'create',enabled:true,label:'生成'},
 {category:'image',action:'edit',enabled:false,label:'編集'},
 {category:'image',action:'delete',enabled:false,label:'削除'},
 {category:'audio',action:'create',enabled:true,label:'生成'},
 {category:'audio',action:'edit',enabled:false,label:'編集'},
 {category:'audio',action:'delete',enabled:false,label:'削除'},
 {category:'music',action:'create',enabled:true,label:'生成'},
 {category:'music',action:'edit',enabled:false,label:'編集'},
 {category:'music',action:'delete',enabled:false,label:'削除'},
 {category:'document',action:'create',enabled:true,label:'生成'},
 {category:'document',action:'edit',enabled:true,label:'編集'},
 {category:'document',action:'delete',enabled:false,label:'削除'},
 {category:'system',action:'create',enabled:false,label:'コマンド実行'},
 {category:'system',action:'edit',enabled:false,label:'外部API呼び出し'},
]

export const CATEGORY_LABELS:Record<ContentCategory,string>={
 code:'コード',
 image:'画像',
 audio:'音声',
 music:'音楽',
 document:'ドキュメント',
 system:'システム'
}
