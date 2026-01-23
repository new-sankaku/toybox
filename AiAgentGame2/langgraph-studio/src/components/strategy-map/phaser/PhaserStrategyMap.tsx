import { useRef,useEffect } from 'react'
import Phaser from 'phaser'
import { createStrategyMapGame } from './game/StrategyMapGame'
import { eventBridge } from './game/utils/EventBridge'
import type { MapAgent,UserNode,Connection } from '../strategyMapTypes'
import type { PhaserMapAgent,PhaserUserNode,PhaserConnection } from './types/phaserTypes'

interface Props {
 agents: readonly MapAgent[]
 user: UserNode
 connections: readonly Connection[]
 width: number
 height: number
}

function convertToPhaserAgent(agent: MapAgent): PhaserMapAgent {
 return {
  id: agent.id,
  type: agent.type,
  status: agent.status,
  parentId: agent.parentId,
  currentTask: agent.currentTask,
  bubble: agent.bubble,
  bubbleType: agent.bubbleType,
  spawnProgress: agent.spawnProgress,
 }
}

function convertToPhaserUser(user: UserNode): PhaserUserNode {
 return {
  x: user.x,
  y: user.y,
  queue: [...user.queue],
 }
}

function convertToPhaserConnection(conn: Connection): PhaserConnection {
 return {
  id: conn.id,
  fromId: conn.fromId,
  toId: conn.toId,
  type: conn.type,
  active: conn.active,
 }
}

export default function PhaserStrategyMap({
 agents,
 user,
 connections,
 width,
 height,
}: Props) {
 const containerRef=useRef<HTMLDivElement>(null)
 const gameRef=useRef<Phaser.Game|null>(null)

 useEffect(()=>{
  const container=containerRef.current
  if (!container||gameRef.current) return

  const dpr=Math.min(window.devicePixelRatio||1,2)
  eventBridge.updateDimensions(width*dpr,height*dpr)
  eventBridge.updateUser(convertToPhaserUser(user))
  eventBridge.updateAgents(agents.map(convertToPhaserAgent))
  eventBridge.updateConnections(connections.map(convertToPhaserConnection))

  gameRef.current=createStrategyMapGame({
   parent: container,
   width,
   height,
  })

  return ()=>{
   if (gameRef.current) {
    gameRef.current.destroy(true)
    gameRef.current=null
   }
  }
 },[])

 useEffect(()=>{
  eventBridge.updateAgents(agents.map(convertToPhaserAgent))
 },[agents])

 useEffect(()=>{
  eventBridge.updateUser(convertToPhaserUser(user))
 },[user])

 useEffect(()=>{
  eventBridge.updateConnections(connections.map(convertToPhaserConnection))
 },[connections])

 useEffect(()=>{
  if (gameRef.current) {
   const dpr=Math.min(window.devicePixelRatio||1,2)
   gameRef.current.scale.resize(width*dpr,height*dpr)
   eventBridge.updateDimensions(width*dpr,height*dpr)
  }
 },[width,height])

 return (
  <div
   ref={containerRef}
   className="w-full h-full cursor-grab active:cursor-grabbing"
   style={{ display: 'block' }}
  />
)
}
