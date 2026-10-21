// /check 에서 쓸 라이브러리 빌드: src/lib.js → webapp/static/vity-face.js
// base 를 '/face/' 로 두는 이유: MediaPipe wasm · 모델을 /face/mediapipe/ 에서 받는다 (server.py 가 이미 거기로 내보낸다).
// 빌드: npm run build:lib  (npm run build 로 /face 앱을 먼저 빌드해 두어야 wasm 이 그 자리에 있다)
import { defineConfig } from 'vite';

export default defineConfig({
  base: '/face/',
  build: {
    lib: { entry: 'src/lib.js', formats: ['es'], fileName: () => 'vity-face.js' },
    outDir: '../static',
    emptyOutDir: false,          // webapp/static 에는 다른 파일이 많다
    sourcemap: true,
    copyPublicDir: false,        // public/ (mediapipe wasm · 아이콘)은 /face 빌드가 이미 내보낸다. static 에 또 복사하지 않는다.
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
