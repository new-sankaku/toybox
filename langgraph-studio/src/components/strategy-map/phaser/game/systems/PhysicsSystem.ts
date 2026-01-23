import { PHYSICS,LAYOUT } from '../../../strategyMapConfig'
import type { PhaserMapAgent,PhaserUserNode,PhysicsBody } from '../../types/phaserTypes'
import { eventBridge } from '../utils/EventBridge'

interface Vec2 {
 x: number
 y: number
}

interface TreeNode {
 id: string
 agent: PhaserMapAgent
 children: TreeNode[]
 depth: number
 subtreeWidth: number
 x: number
 y: number
}

export class PhysicsSystem {
 private positions: Map<string,PhysicsBody>=new Map()
 private width: number=1000
 private height: number=700
 private initialized: boolean=false

 setDimensions(width: number,height: number): void {
  this.width=width
  this.height=height
 }

 restorePositions(): void {
  if (this.initialized) return
  this.initialized=true
  const saved=eventBridge.getSavedPositions()
  if (saved.size>0) {
   saved.forEach((pos,id)=>{
    this.positions.set(id,{ ...pos })
   })
  }
 }

 savePositions(): void {
  eventBridge.savePositions(this.positions)
 }

 getPosition(id: string): PhysicsBody|undefined {
  return this.positions.get(id)
 }

 getAllPositions(): Map<string,PhysicsBody>{
  return this.positions
 }

 private buildTree(agents: readonly PhaserMapAgent[]): TreeNode[] {
  const nodeMap=new Map<string,TreeNode>()
  const roots: TreeNode[]=[]

  for (const agent of agents) {
   if (agent.status==='waiting_approval') continue
   nodeMap.set(agent.id,{
    id: agent.id,
    agent,
    children: [],
    depth: 0,
    subtreeWidth: 0,
    x: 0,
    y: 0,
   })
  }

  for (const agent of agents) {
   if (agent.status==='waiting_approval') continue
   const node=nodeMap.get(agent.id)
   if (!node) continue
   if (agent.parentId&&nodeMap.has(agent.parentId)) {
    const parent=nodeMap.get(agent.parentId)!
    parent.children.push(node)
   } else {
    roots.push(node)
   }
  }

  const setDepth=(node: TreeNode,depth: number): void=>{
   node.depth=depth
   for (const child of node.children) {
    setDepth(child,depth+1)
   }
  }
  for (const root of roots) {
   setDepth(root,0)
  }

  return roots
 }

 private calcSubtreeWidth(node: TreeNode,spacing: number): number {
  if (node.children.length===0) {
   node.subtreeWidth=spacing
   return spacing
  }
  let total=0
  for (const child of node.children) {
   total+=this.calcSubtreeWidth(child,spacing)
  }
  node.subtreeWidth=Math.max(spacing,total)
  return node.subtreeWidth
 }

 private assignPositions(
  node: TreeNode,
  startX: number,
  baseY: number,
  levelHeight: number,
  result: Map<string,Vec2>
): void {
  const y=baseY+node.depth*levelHeight
  const x=startX+node.subtreeWidth/2
  result.set(node.id,{ x,y })
  node.x=x
  node.y=y

  let childX=startX
  for (const child of node.children) {
   this.assignPositions(child,childX,baseY,levelHeight,result)
   childX+=child.subtreeWidth
  }
 }

 private treePositions: Map<string,Vec2>=new Map()
 private cachedTargets: Map<string,Vec2>=new Map()
 private agentParents: Map<string,string|null>=new Map()

 computeAgentTarget(
  agent: PhaserMapAgent,
  allAgents: readonly PhaserMapAgent[],
  user: PhaserUserNode
): Vec2 {
  if (agent.status==='waiting_approval') {
   const waiting=allAgents.filter(a=>a.status==='waiting_approval')
   const idx=waiting.findIndex(a=>a.id===agent.id)
   const count=waiting.length
   const arcRadius=100
   const arcSpread=Math.min(Math.PI*0.6,count*0.25)
   const startAngle=Math.PI+(Math.PI-arcSpread)/2
   const angleStep=count>1 ? arcSpread/(count-1) : 0
   const angle=startAngle+idx*angleStep
   return {
    x: user.x+Math.cos(angle)*arcRadius,
    y: user.y+Math.sin(angle)*arcRadius*0.6,
   }
  }

  const cached=this.cachedTargets.get(agent.id)
  const oldParent=this.agentParents.get(agent.id)
  const parentChanged=oldParent!==agent.parentId

  if (cached&&!parentChanged) {
   return cached
  }

  this.agentParents.set(agent.id,agent.parentId??null)

  const nonWaiting=allAgents.filter(a=>a.status!=='waiting_approval')
  this.rebuildTreeLayout(nonWaiting)

  const pos=this.treePositions.get(agent.id)
  if (pos) {
   this.cachedTargets.set(agent.id,pos)
   return pos
  }

  const fallback={ x: this.width/2,y: this.height*0.1 }
  this.cachedTargets.set(agent.id,fallback)
  return fallback
 }

 private rebuildTreeLayout(agents: readonly PhaserMapAgent[]): void {
  this.treePositions.clear()
  const roots=this.buildTree(agents)
  if (roots.length===0) return

  const spacing=80
  const levelHeight=90
  const baseY=this.height*0.08

  let totalWidth=0
  for (const root of roots) {
   totalWidth+=this.calcSubtreeWidth(root,spacing)
  }

  let startX=(this.width-totalWidth)/2
  for (const root of roots) {
   this.assignPositions(root,startX,baseY,levelHeight,this.treePositions)
   startX+=root.subtreeWidth
  }
 }

 clearCachedTarget(agentId: string): void {
  this.cachedTargets.delete(agentId)
  this.agentParents.delete(agentId)
 }

 private findAvoidanceDirection(
  currentId: string,
  pos: PhysicsBody,
  dirX: number,
  dirY: number
): Vec2 {
  const avoidRadius=PHYSICS.REPULSION_RADIUS
  const avoidRadiusSq=avoidRadius*avoidRadius*4
  let closestDistSq=Infinity
  let closestX=0
  let closestY=0

  this.positions.forEach((other,otherId)=>{
   if (otherId===currentId) return
   const toOtherX=other.x-pos.x
   const toOtherY=other.y-pos.y
   const distSq=toOtherX*toOtherX+toOtherY*toOtherY
   if (distSq<avoidRadiusSq&&distSq>PHYSICS.EPSILON) {
    const dotProduct=dirX*toOtherX+dirY*toOtherY
    if (dotProduct>0&&distSq<closestDistSq) {
     closestDistSq=distSq
     closestX=other.x
     closestY=other.y
    }
   }
  })

  if (closestDistSq===Infinity) return { x: dirX,y: dirY }

  const toObsX=closestX-pos.x
  const toObsY=closestY-pos.y
  const perpX=-toObsY
  const perpY=toObsX
  const perpLenSq=perpX*perpX+perpY*perpY

  if (perpLenSq<PHYSICS.EPSILON) return { x: dirX,y: dirY }

  const perpLen=Math.sqrt(perpLenSq)
  const normPerpX=perpX/perpLen
  const normPerpY=perpY/perpLen
  const cross=dirX*toObsY-dirY*toObsX
  const sign=cross>=0 ? 1 :-1
  const strength=PHYSICS.AVOIDANCE_STRENGTH
  const newDirX=dirX*(1-strength)+normPerpX*sign*strength
  const newDirY=dirY*(1-strength)+normPerpY*sign*strength
  const lenSq=newDirX*newDirX+newDirY*newDirY

  if (lenSq<PHYSICS.EPSILON) return { x: dirX,y: dirY }

  const len=Math.sqrt(lenSq)
  return { x: newDirX/len,y: newDirY/len }
 }

 updatePositions(agents: readonly PhaserMapAgent[],user: PhaserUserNode): Set<string>{
  this.restorePositions()
  const currentIds=new Set(agents.map(a=>a.id))
  const newAgentIds=new Set<string>()

  for (const agent of agents) {
   const target=this.computeAgentTarget(agent,agents,user)

   let pos=this.positions.get(agent.id)
   if (!pos) {
    pos={
     x: target.x,
     y: target.y,
     vx: 0,
     vy: 0,
     targetX: target.x,
     targetY: target.y,
    }
    this.positions.set(agent.id,pos)
    newAgentIds.add(agent.id)
   } else {
    pos.targetX=target.x
    pos.targetY=target.y
   }
  }

  const removedIds=new Set<string>()
  this.positions.forEach((_,id)=>{
   if (!currentIds.has(id)) {
    removedIds.add(id)
   }
  })

  removedIds.forEach(id=>{
   this.positions.delete(id)
   this.cachedTargets.delete(id)
   this.agentParents.delete(id)
  })

  this.positions.forEach((pos,id)=>{
   this.updatePhysics(id,pos)
  })

  return newAgentIds
 }

 private updatePhysics(_id: string,pos: PhysicsBody): void {
  const dx=pos.targetX-pos.x
  const dy=pos.targetY-pos.y
  const distSq=dx*dx+dy*dy

  if (distSq<4) {
   pos.x=pos.targetX
   pos.y=pos.targetY
   pos.vx=0
   pos.vy=0
   return
  }

  const dist=Math.sqrt(distSq)
  const dirX=dx/dist
  const dirY=dy/dist

  const accel=Math.min(dist*PHYSICS.SPRING_STIFFNESS,3)
  pos.vx+=dirX*accel
  pos.vy+=dirY*accel
  pos.vx*=PHYSICS.DAMPING
  pos.vy*=PHYSICS.DAMPING

  if (Math.abs(pos.vx)<PHYSICS.MIN_VELOCITY) pos.vx=0
  if (Math.abs(pos.vy)<PHYSICS.MIN_VELOCITY) pos.vy=0

  pos.x+=pos.vx
  pos.y+=pos.vy
 }

 getRemovedPositions(currentIds: Set<string>): Map<string,PhysicsBody>{
  const removed=new Map<string,PhysicsBody>()
  this.positions.forEach((pos,id)=>{
   if (!currentIds.has(id)) {
    removed.set(id,{ ...pos })
   }
  })
  return removed
 }

 destroy(): void {
  this.savePositions()
  this.positions.clear()
 }
}
