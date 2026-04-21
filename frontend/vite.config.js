import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true,
    allowedHosts: true,
    // proxy: {
    //   '/conceive': 'http://localhost:8000',
    //   '/species': 'http://localhost:8000',
    //   '/cradle': 'http://localhost:8000',
    //   '/system': 'http://localhost:8000',
    //   '/health': 'http://localhost:8000',
    //   '/babies': 'http://localhost:8000',
    //   '/translate': 'http://localhost:8000',
    // },
  },
})

