const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'yl-plugin-'));
try{
 const sandbox={module:{exports:{}},process,require(name){if(name==='obsidian')return {Plugin:class{},ItemView:class{},PluginSettingTab:class{}};if(name==='os')return {homedir:()=>root};return require(name)}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../plugin/main.js'),'utf8'),sandbox);
 const plugin=new sandbox.module.exports();plugin.settings={name:'演示助手'};plugin.app={vault:{adapter:{getBasePath:()=>path.join(root,'vault')}}};
 plugin.configure();const profilePath=plugin.config.profilePath;
 let config=JSON.parse(fs.readFileSync(profilePath));config.workbench.exclude_folders=['保密'];config.extra={preserve:true};fs.writeFileSync(profilePath,JSON.stringify(config));
 plugin.settings={model:'another-model'};plugin.configure();config=JSON.parse(fs.readFileSync(profilePath));
 assert.equal(config.workbench.name,'演示助手');assert.deepEqual(config.workbench.exclude_folders,['保密']);assert.equal(config.extra.preserve,true);assert.equal(config.workbench.model,'another-model');
 console.log('Plugin settings preservation: PASS');
}finally{fs.rmSync(root,{recursive:true,force:true})}
