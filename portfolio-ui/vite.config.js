import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(),tailwindcss()],
  server: {
    port: 3000, // The port your frontend runs on locally
    proxy: {
      // Intercept any request starting with /api
      '/api': {
        target: 'http://localhost:8000', // Forward to local FastAPI backend
        changeOrigin: true,
        secure: false,
        // Optional: Remove /api prefix before hitting FastAPI if your
        // FastAPI routes don't explicitly start with /api
        //rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
