import type{AgentType,AgentStatus}from'../../types/agent'

export interface MapAgent{
 id:string
 type:AgentType
 status:AgentStatus
 parentId:string|null
 x:number
 y:number
 targetX:number
 targetY:number
 currentTask:string|null
 bubble:string|null
 bubbleType:'info'|'question'|'success'|'warning'|null
 isSpawning:boolean
 spawnProgress:number
 workingFrame:number
 aiTarget:string|null
}

export interface AIService{
 id:string
 name:string
 icon:string
 x:number
 y:number
 color:string
}

export interface UserNode{
 x:number
 y:number
 queue:string[]
}

export interface Connection{
 id:string
 fromId:string
 toId:string
 type:'instruction'|'confirm'|'delivery'|'ai-request'|'user-contact'
 progress:number
 active:boolean
}

export interface MapState{
 agents:MapAgent[]
 aiServices:AIService[]
 user:UserNode
 connections:Connection[]
 viewOffset:{x:number,y:number}
 zoom:number
}

export type MapAction=
 |{type:'SPAWN_AGENT',agent:MapAgent}
 |{type:'REMOVE_AGENT',id:string}
 |{type:'UPDATE_AGENT',id:string,updates:Partial<MapAgent>}
 |{type:'ADD_CONNECTION',connection:Connection}
 |{type:'REMOVE_CONNECTION',id:string}
 |{type:'UPDATE_CONNECTION',id:string,updates:Partial<Connection>}
 |{type:'SET_VIEW',offset:{x:number,y:number},zoom:number}
 |{type:'TICK'}
