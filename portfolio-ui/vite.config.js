import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(),tailwindcss()],
  server: {
    port: 5173, // The port your frontend runs in docker-compose
    proxy: {
      // Intercept any request starting with /api
      '/api': { //redirect to backend container
        target: 'http://portfolio-api:8000', // Forward to containerized FastAPI backend
        changeOrigin: true,
        secure: false,
        // Optional: Remove /api prefix before hitting FastAPI if your
        // FastAPI routes don't explicitly start with /api
        //rewrite: (path) => path.replace(/^\/api/, '')
      }
    }
  }
})
