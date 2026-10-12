import {build} from 'esbuild';
import {mkdir,writeFile} from 'node:fs/promises';
await mkdir('dist',{recursive:true});
await build({entryPoints:['ui/main.jsx'],bundle:true,outdir:'dist',minify:true,sourcemap:false,jsx:'automatic',loader:{'.png':'file'},define:{'process.env.NODE_ENV':'"production"'}});
await writeFile('dist/index.html','<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>知识工作台</title><link rel="stylesheet" href="/main.css"></head><body><div id="root"></div><script src="/main.js"></script></body></html>');
console.log('Workbench build complete');
