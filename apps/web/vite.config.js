import { fileURLToPath, URL } from 'node:url';
import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';
export default defineConfig({
    plugins: [vue()],
    server: {
        proxy: {
            '/api': { target: 'http://127.0.0.1:8001', changeOrigin: false },
            '/health': { target: 'http://127.0.0.1:8001', changeOrigin: false },
            '/ws': { target: 'ws://127.0.0.1:8001', ws: true },
        },
    },
    resolve: {
        alias: {
            '@': fileURLToPath(new URL('./src', import.meta.url)),
        },
    },
});
