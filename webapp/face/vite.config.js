import { defineConfig } from 'vite';
export default defineConfig({
  server: { host: true, port: 5173, https: false },
  build: { outDir: 'dist', target: 'es2020' },
  test: { environment: 'node' },
});
