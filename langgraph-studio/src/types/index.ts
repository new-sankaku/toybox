export*from'./project'
export*from'./agent'
export*from'./checkpoint'
export*from'./intervention'
export*from'./uploadedFile'
export*from'./autoApproval'
export*from'./aiProvider'
export*from'./brushup'

export interface ElectronAPI{
 backend:{
  start:()=>Promise<{success:boolean;port?:number;error?:string}>
  stop:()=>Promise<{success:boolean}>
  status:()=>Promise<{running:boolean;port:number|null}>
  getPort:()=>Promise<number|null>
 }
 app:{
  getVersion:()=>Promise<string>
  getPlatform:()=>Promise<NodeJS.Platform>
 }
 on:(channel:string,callback:(...args:unknown[])=>void)=>void
 off:(channel:string,callback:(...args:unknown[])=>void)=>void
}

declare global{
 interface Window{
  electron:ElectronAPI
 }
}
