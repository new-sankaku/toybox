import '@testing-library/jest-dom/vitest'

Object.defineProperty(window,'matchMedia',{
 writable:true,
 value:(query:string)=>({
  matches:false,
  media:query,
  onchange:null,
  addListener:()=>{},
  removeListener:()=>{},
  addEventListener:()=>{},
  removeEventListener:()=>{},
  dispatchEvent:()=>false
 })
})

Object.defineProperty(window,'ResizeObserver',{
 writable:true,
 value:class ResizeObserver{
  observe(){}
  unobserve(){}
  disconnect(){}
 }
})
