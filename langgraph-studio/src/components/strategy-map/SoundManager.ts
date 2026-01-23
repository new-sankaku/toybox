type SoundType='spawn'|'complete'|'approval'|'error'|'click'|'phase'

export class SoundManager {
 private audioContext: AudioContext|null=null
 private enabled: boolean=false
 private volume: number=0.3

 private getContext(): AudioContext {
  if (!this.audioContext) {
   this.audioContext=new AudioContext()
  }
  return this.audioContext
 }

 setEnabled(enabled: boolean): void {
  this.enabled=enabled
 }

 setVolume(volume: number): void {
  this.volume=Math.max(0,Math.min(1,volume))
 }

 play(type: SoundType): void {
  if (!this.enabled) return

  try {
   const ctx=this.getContext()
   if (ctx.state==='suspended') {
    ctx.resume()
   }

   switch (type) {
    case 'spawn':
     this.playSpawnSound(ctx)
     break
    case 'complete':
     this.playCompleteSound(ctx)
     break
    case 'approval':
     this.playApprovalSound(ctx)
     break
    case 'error':
     this.playErrorSound(ctx)
     break
    case 'click':
     this.playClickSound(ctx)
     break
    case 'phase':
     this.playPhaseSound(ctx)
     break
   }
  } catch (e) {
   console.warn('Sound play failed:',e)
  }
 }

 private playSpawnSound(ctx: AudioContext): void {
  const now=ctx.currentTime
  const osc=ctx.createOscillator()
  const gain=ctx.createGain()

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.type='sine'
  osc.frequency.setValueAtTime(200,now)
  osc.frequency.exponentialRampToValueAtTime(600,now+0.1)
  osc.frequency.exponentialRampToValueAtTime(400,now+0.2)

  gain.gain.setValueAtTime(this.volume*0.5,now)
  gain.gain.exponentialRampToValueAtTime(0.01,now+0.3)

  osc.start(now)
  osc.stop(now+0.3)
 }

 private playCompleteSound(ctx: AudioContext): void {
  const now=ctx.currentTime

  const notes=[523.25,659.25,783.99]
  notes.forEach((freq,i)=>{
   const osc=ctx.createOscillator()
   const gain=ctx.createGain()

   osc.connect(gain)
   gain.connect(ctx.destination)

   osc.type='sine'
   osc.frequency.setValueAtTime(freq,now)

   const startTime=now+i*0.08
   gain.gain.setValueAtTime(0,startTime)
   gain.gain.linearRampToValueAtTime(this.volume*0.4,startTime+0.02)
   gain.gain.exponentialRampToValueAtTime(0.01,startTime+0.2)

   osc.start(startTime)
   osc.stop(startTime+0.25)
  })
 }

 private playApprovalSound(ctx: AudioContext): void {
  const now=ctx.currentTime

  for (let i=0;i<3;i++) {
   const osc=ctx.createOscillator()
   const gain=ctx.createGain()

   osc.connect(gain)
   gain.connect(ctx.destination)

   osc.type='sine'
   const startTime=now+i*0.15
   osc.frequency.setValueAtTime(880,startTime)

   gain.gain.setValueAtTime(0,startTime)
   gain.gain.linearRampToValueAtTime(this.volume*0.3,startTime+0.02)
   gain.gain.exponentialRampToValueAtTime(0.01,startTime+0.1)

   osc.start(startTime)
   osc.stop(startTime+0.12)
  }
 }

 private playErrorSound(ctx: AudioContext): void {
  const now=ctx.currentTime
  const osc=ctx.createOscillator()
  const gain=ctx.createGain()

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.type='sawtooth'
  osc.frequency.setValueAtTime(200,now)
  osc.frequency.linearRampToValueAtTime(100,now+0.3)

  gain.gain.setValueAtTime(this.volume*0.3,now)
  gain.gain.exponentialRampToValueAtTime(0.01,now+0.4)

  osc.start(now)
  osc.stop(now+0.4)
 }

 private playClickSound(ctx: AudioContext): void {
  const now=ctx.currentTime
  const osc=ctx.createOscillator()
  const gain=ctx.createGain()

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.type='sine'
  osc.frequency.setValueAtTime(1000,now)

  gain.gain.setValueAtTime(this.volume*0.2,now)
  gain.gain.exponentialRampToValueAtTime(0.01,now+0.05)

  osc.start(now)
  osc.stop(now+0.06)
 }

 private playPhaseSound(ctx: AudioContext): void {
  const now=ctx.currentTime

  const notes=[392,523.25,659.25,783.99]
  notes.forEach((freq,i)=>{
   const osc=ctx.createOscillator()
   const gain=ctx.createGain()

   osc.connect(gain)
   gain.connect(ctx.destination)

   osc.type='triangle'
   osc.frequency.setValueAtTime(freq,now)

   const startTime=now+i*0.1
   gain.gain.setValueAtTime(0,startTime)
   gain.gain.linearRampToValueAtTime(this.volume*0.35,startTime+0.03)
   gain.gain.exponentialRampToValueAtTime(0.01,startTime+0.3)

   osc.start(startTime)
   osc.stop(startTime+0.35)
  })
 }

 destroy(): void {
  if (this.audioContext) {
   this.audioContext.close()
   this.audioContext=null
  }
 }

 dispose(): void {
  this.destroy()
 }
}

export const soundManager=new SoundManager()
