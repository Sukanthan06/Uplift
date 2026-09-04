import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    // Native fs events from a Windows-host bind mount don't reach chokidar
    // inside the Linux container -- without polling, HMR silently serves a
    // stale bundle after every edit instead of picking up the change.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
})
