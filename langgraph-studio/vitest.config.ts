import {resolve} from 'path'
import {defineConfig} from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
 plugins:[react()],
 test:{
  environment:'jsdom',
  globals:true,
  setupFiles:['./src/test/setup.ts'],
  include:['src/**/*.{test,spec}.{js,ts,jsx,tsx}'],
  exclude:['node_modules','dist','out','tests'],
  coverage:{
   provider:'v8',
   reporter:['text','json','html'],
   reportsDirectory:'./coverage',
   exclude:[
    'node_modules/',
    'src/test/',
    '**/*.d.ts',
    '**/*.config.*',
    '**/types/',
   ]
  }
 },
 resolve:{
  alias:{
   '@':resolve(__dirname,'src'),
   '@components':resolve(__dirname,'src/components'),
   '@stores':resolve(__dirname,'src/stores'),
   '@hooks':resolve(__dirname,'src/hooks'),
   '@services':resolve(__dirname,'src/services'),
   '@types':resolve(__dirname,'src/types')
  }
 }
})
