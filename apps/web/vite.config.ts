import { fileURLToPath, URL } from 'node:url'
import process from 'node:process'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18000',
        changeOrigin: false,
        headers: { 'X-Rover-Voice-Token': process.env.ROVER_VOICE_GATEWAY_TOKEN ?? '' },
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
