import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 3000,
    proxy: {
      '/api/tiles/carto': {
        target: 'https://basemaps.cartocdn.com',
        changeOrigin: true,
        rewrite: (path) => {
          let stripped = path.replace(/^\/api\/tiles\/carto/, '');
          if (stripped.startsWith('/voyager')) {
            stripped = '/rastertiles' + stripped;
          }
          return stripped.endsWith('.png') ? stripped : `${stripped}.png`;
        }
      }
    }
  }
});
