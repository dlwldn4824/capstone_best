import { defineConfig } from 'vite';
import { createReadStream, statSync } from 'node:fs';
import { extname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

// 캐릭터 · 글꼴은 base 밖의 /assets/… 로 부른다 (scripts/sync-assets.mjs 참고).
// 개발 서버 · preview 에서는 shared-assets/ 사본을 그 주소로 내보낸다.
const ASSETS = resolve(fileURLToPath(new URL('.', import.meta.url)), 'shared-assets');
const TYPES = { '.png': 'image/png', '.woff2': 'font/woff2', '.otf': 'font/otf' };
function serveAssets(req, res, next) {
  const f = join(ASSETS, decodeURIComponent((req.url || '').split('?')[0]));
  if (!f.startsWith(ASSETS + sep)) return next();
  try { if (!statSync(f).isFile()) return next(); } catch { return next(); }
  res.setHeader('Content-Type', TYPES[extname(f)] || 'application/octet-stream');
  createReadStream(f).pipe(res);
}
const sharedAssets = {
  name: 'shared-assets',
  configureServer: s => { s.middlewares.use('/assets', serveAssets); },
  configurePreviewServer: s => { s.middlewares.use('/assets', serveAssets); },
};

// /face/ 아래에서 서빙한다 (webapp/server.py · 단독 nginx 모두).
export default defineConfig({
  base: '/face/',
  plugins: [sharedAssets],
  server: { host: true, port: 5173, https: false },
  build: { outDir: 'dist', target: 'es2020' },
  test: { environment: 'node' },
});
