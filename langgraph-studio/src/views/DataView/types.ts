import{Image,Music,Play,FileText,Code}from'lucide-react'
import{type ApiAsset}from'@/services/apiService'

export type AssetType='image'|'audio'|'video'|'document'|'code'|'other'
export type ViewMode='grid'|'list'
export type ApprovalStatus='approved'|'pending'|'rejected'
export type ApprovalFilter='all'|'approved'|'pending'|'rejected'

export interface Asset{
 id:string
 agentId?:string
 name:string
 type:AssetType
 agent:string
 size:string
 createdAt:string
 url?:string
 thumbnail?:string
 duration?:string
 content?:string
 approvalStatus:ApprovalStatus
}

export function convertApiAsset(apiAsset:ApiAsset):Asset{
 return{
  id:apiAsset.id,
  agentId:apiAsset.agentId||undefined,
  name:apiAsset.name,
  type:apiAsset.type,
  agent:apiAsset.agent,
  size:apiAsset.size,
  createdAt:apiAsset.createdAt,
  url:apiAsset.url||undefined,
  thumbnail:apiAsset.thumbnail||undefined,
  duration:apiAsset.duration||undefined,
  content:apiAsset.content||undefined,
  approvalStatus:apiAsset.approvalStatus,
 }
}

export const approvalStatusClasses:Record<ApprovalStatus,string>={
 approved:'nier-status-badge-approved',
 pending:'nier-status-badge-pending',
 rejected:'nier-status-badge-rejected'
}

export const typeIcons:Record<AssetType,typeof Image>={
 image:Image,
 audio:Music,
 video:Play,
 document:FileText,
 code:Code,
 other:FileText
}

export const typeColors:Record<AssetType,string>={
 image:'text-nier-text-light',
 audio:'text-nier-text-light',
 video:'text-nier-text-light',
 document:'text-nier-text-light',
 code:'text-nier-text-light',
 other:'text-nier-text-light'
}
