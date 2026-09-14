const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const script=fs.readFileSync('jarvis/api/ui/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
function element(tag='div'){return {tagName:tag.toUpperCase(),children:[],textContent:'',dataset:{},style:{setProperty(){}},classList:{add(){},remove(){},toggle(){}},setAttribute(){},addEventListener(){},focus(){},append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=[...nodes];},remove(){}};}
const nodes=new Map();const document={querySelectorAll(){return [];},querySelector(key){if(!nodes.has(key))nodes.set(key,element());return nodes.get(key);},createElement:element,createTextNode:text=>({textContent:text}),addEventListener(){}};
let reply={response:'Hello **friend**'},speechCalls=0,uploadCalls=0,audioPaused=false;
class FakeAudio{constructor(){this.paused=true;}async play(){this.paused=false;this.onplaying?.();}pause(){audioPaused=true;this.paused=true;}}
class FakeContext{resume(){return Promise.resolve();}createMediaElementSource(){return {connect(){},disconnect(){}};}createAnalyser(){return {fftSize:256,connect(){},getByteTimeDomainData(data){data.fill(150);}};}}
const context={document,window:{AudioContext:FakeContext,addEventListener(){}},Audio:FakeAudio,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},AbortController,AbortSignal,console,performance,setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){},fetch:async url=>{
 if(url==='/speech'){speechCalls++;return {ok:true,blob:async()=>({})};}
 if(url==='/analyze-upload'){uploadCalls++;return {ok:true,json:async()=>({answer:'A test attachment.'})};}
 return {ok:true,json:async()=>url==='/chat'?reply:url==='/runtime'?{connection:'ready',voice:'en_US-amy-medium',engine:'Piper',voice_enabled:true}:{hardware:{},model:'test'}};
}};
vm.createContext(context);vm.runInContext(script,context);
(async()=>{
 await new Promise(setImmediate);
 assert.equal(vm.runInContext("extractWakeCommand('Hey Jarvis, what time is it?')",context),'what time is it?');
 assert.equal(vm.runInContext("extractWakeCommand('Jarvis')",context),'');
 assert.equal(vm.runInContext("extractWakeCommand('ordinary background speech')",context),null);
 assert.equal(vm.runInContext("speechText('## **All done!** 😊 [Open it](https://example.com)')",context),'All done! Open it');
 vm.runInContext('muted=true',context);await vm.runInContext("send('hello')",context);
 assert.equal(speechCalls,0);assert.equal(vm.runInContext('busy',context),false);
 assert.match(nodes.get('#reply-time').textContent,/Last reply:/);
 context.file={name:'notes.txt',size:12};vm.runInContext('attachUpload(file)',context);
 assert.equal(uploadCalls,0);assert.equal(vm.runInContext('attachedFile.name',context),'notes.txt');
 await vm.runInContext("send('What is this about?')",context);assert.equal(uploadCalls,1);assert.equal(vm.runInContext('attachedFile',context),null);
 const box=element();context.box=box;vm.runInContext("markdown(box,'# Heading\\n- **bold**\\n- `code`\\n<img src=x onerror=alert(1)>')",context);
 assert.equal(box.children[0].tagName,'H3');assert.equal(box.children[1].tagName,'UL');assert.equal(box.children[1].children[0].children[1].tagName,'STRONG');
 assert.ok(JSON.stringify(box).includes('<img src=x'));assert.ok(!JSON.stringify(box).includes('"tagName":"IMG"'));
 vm.runInContext('muted=false',context);await vm.runInContext("speak('hello')",context);assert.equal(vm.runInContext('speaking',context),true);
 vm.runInContext('stopVoice()',context);assert.equal(vm.runInContext('speaking||preparing',context),false);assert.ok(audioPaused);
 reply={response:''};await vm.runInContext("send('hello')",context);assert.equal(vm.runInContext('busy',context),false);assert.equal(nodes.get('#command-form button[type=submit]').disabled,false);
 console.log('PASS: attachment waits for a command; mute; reply timing; safe Markdown; playback cleanup; empty-reply recovery.');
})().catch(e=>{console.error(e);process.exitCode=1;});
