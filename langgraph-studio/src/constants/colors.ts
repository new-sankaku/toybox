export const COLORS={
 status:{
  completed:{bg:'#A8A090',border:'#454138',text:'#454138'},
  running:{bg:'#C4956C',border:'#8B6914',text:'#454138'},
  waitingApproval:{bg:'#D4C896',border:'#8B7914',text:'#454138'},
  failed:{bg:'#B85C5C',border:'#8B2020',text:'#E8E4D4'},
  pending:{bg:'#E8E4D4',border:'rgba(69, 65, 56, 0.3)',text:'#8A8578'}
 },
 progress:{
  completed:'#7AAA7A',
  running:'#8B6914'
 },
 badge:{
  waitingApproval:'#8B7914'
 },
 edge:{
  completed:'rgba(69, 65, 56, 0.5)',
  running:'#C4956C',
  default:'rgba(69, 65, 56, 0.15)'
 },
 canvas:{
  phaseGroup:{
   bg:'rgba(69, 65, 56, 0.04)',
   border:'rgba(69, 65, 56, 0.2)',
   text:'#5A5548'
  },
  background:'rgba(69, 65, 56, 0.08)'
 }
}as const

export type StatusColorKey=keyof typeof COLORS.status
