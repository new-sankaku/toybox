import type {
 PhaserMapAgent,
 PhaserUserNode,
 PhaserConnection,
 PhysicsBody,
 EventType,
 EventPayload
} from '../../types/phaserTypes'

type EventCallback<T extends EventType>=(payload: EventPayload[T])=>void

class EventBridge {
 private listeners: Map<EventType,Set<EventCallback<EventType>>>=new Map()
 private agents: PhaserMapAgent[]=[]
 private user: PhaserUserNode={ x: 0,y: 0,queue: [] }
 private connections: PhaserConnection[]=[]
 private dimensions: { width: number;height: number }={ width: 1000,height: 700 }
 private savedPositions: Map<string,PhysicsBody>=new Map()

 on<T extends EventType>(event: T,callback: EventCallback<T>): void {
  if (!this.listeners.has(event)) {
   this.listeners.set(event,new Set())
  }
  this.listeners.get(event)!.add(callback as EventCallback<EventType>)
 }

 off<T extends EventType>(event: T,callback: EventCallback<T>): void {
  const callbacks=this.listeners.get(event)
  if (callbacks) {
   callbacks.delete(callback as EventCallback<EventType>)
  }
 }

 private emit<T extends EventType>(event: T,payload: EventPayload[T]): void {
  const callbacks=this.listeners.get(event)
  if (callbacks) {
   callbacks.forEach(cb=>cb(payload))
  }
 }

 updateAgents(agents: PhaserMapAgent[]): void {
  this.agents=agents
  this.emit('agents-updated',agents)
 }

 updateUser(user: PhaserUserNode): void {
  this.user=user
  this.emit('user-updated',user)
 }

 updateConnections(connections: PhaserConnection[]): void {
  this.connections=connections
  this.emit('connections-updated',connections)
 }

 updateDimensions(width: number,height: number): void {
  this.dimensions={ width,height }
  this.emit('resize',{ width,height })
 }

 getAgents(): PhaserMapAgent[] {
  return this.agents
 }

 getUser(): PhaserUserNode {
  return this.user
 }

 getConnections(): PhaserConnection[] {
  return this.connections
 }

 getDimensions(): { width: number;height: number } {
  return this.dimensions
 }

 savePositions(positions: Map<string,PhysicsBody>): void {
  this.savedPositions.clear()
  positions.forEach((pos,id)=>{
   this.savedPositions.set(id,{ ...pos })
  })
 }

 getSavedPositions(): Map<string,PhysicsBody>{
  return this.savedPositions
 }

 destroy(): void {
  this.listeners.clear()
  this.agents=[]
  this.connections=[]
 }
}

export const eventBridge=new EventBridge()
