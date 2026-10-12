// Bundles the TypeScript entry points and assembles an unpacked extension in dist/
// (load it via chrome://extensions → "Load unpacked" → extension/dist).
import { build } from 'esbuild'
import { cpSync, mkdirSync, rmSync } from 'node:fs'

rmSync('dist', { recursive: true, force: true })
mkdirSync('dist', { recursive: true })

const common = { bundle: true, target: 'chrome120', logLevel: 'info' }
// The manifest declares the service worker as a module; content scripts must be classic scripts
await build({ ...common, entryPoints: ['src/background/service-worker.ts'], outfile: 'dist/background/service-worker.js', format: 'esm' })
await build({ ...common, entryPoints: ['src/content/recorder.ts'], outfile: 'dist/content/recorder.js', format: 'iife' })

for (const path of ['manifest.json', 'popup', 'icons']) {
  cpSync(path, `dist/${path}`, { recursive: true })
}
console.log('Extension built → extension/dist')
