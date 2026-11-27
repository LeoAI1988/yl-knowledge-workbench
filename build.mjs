import {build} from 'esbuild';
import {mkdir,writeFile,copyFile,readFile} from 'node:fs/promises';
await mkdir('dist',{recursive:true});
await build({entryPoints:['ui/main.jsx'],bundle:true,outdir:'dist',minify:true,sourcemap:false,jsx:'automatic',loader:{'.png':'file'},define:{'process.env.NODE_ENV':'"production"'}});
await writeFile('dist/index.html','<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>知识工作台</title><link rel="stylesheet" href="/main.css"><script defer src="/workbench-route.js"></script></head><body><div id="root"></div><script src="/main.js"></script></body></html>');
for (const name of ['workbench-route.js','personal-library.js']) await copyFile('ui/'+name,'dist/'+name);
const management=await readFile('ui/personal-library.html','utf8');
await writeFile('dist/personal-library.html',management.replace('</head>','<script defer src="/workbench-route.js"></script></head>'));
console.log('Workbench build complete');
