import {describe,it,expect} from 'vitest'

describe('Example Test Suite',()=>{
 it('should pass basic assertion',()=>{
  expect(1+1).toBe(2)
 })

 it('should handle string operations',()=>{
  const str='hello world'
  expect(str).toContain('hello')
  expect(str.toUpperCase()).toBe('HELLO WORLD')
 })

 it('should handle array operations',()=>{
  const arr=[1,2,3,4,5]
  expect(arr).toHaveLength(5)
  expect(arr.filter(n=>n>2)).toEqual([3,4,5])
 })

 it('should handle object matching',()=>{
  const obj={name:'test',value:42}
  expect(obj).toMatchObject({name:'test'})
  expect(obj).toHaveProperty('value',42)
 })
})
