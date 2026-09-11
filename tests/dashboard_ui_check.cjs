const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('jarvis/api/ui/index.html', 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function element() {
  return {children:[],textContent:'',style:{},dataset:{},classList:{add(){},remove(){},toggle(){}},
    setAttribute(){},addEventListener(){},append(...items){this.children.push(...items);},
    appendChild(item){this.children.push(item);this.lastElementChild=item;}, remove(){}};
}
async function scenario(reply, expected, networkError=false) {
  const nodes = new Map();
  const timers = new Map();let id=0;let chatCalls=0;
  const document = {querySelector(key){if(!nodes.has(key))nodes.set(key,element());return nodes.get(key);},createElement:element,addEventListener(){}};
  const context = {document,window:{},console:{log(){},error(){}},AbortController,
    setTimeout(fn,ms){timers.set(++id,{fn,ms});return id;},clearTimeout(key){timers.delete(key);},setInterval(){},
    fetch:async (url) => {
      if(url==='/chat'){chatCalls++;if(networkError)throw new Error('Network unavailable');return {ok:reply.ok,text:async()=>reply.body};}
      return {ok:true,json:async()=>url==='/tasks'?[]:{status:'online',hardware:{}}};
    }};
  vm.createContext(context);vm.runInContext(script,context);
  await vm.runInContext("sendVoiceMessage('hello')",context);
  const messages = nodes.get('#transcript').children.filter(x=>x.className?.startsWith('message'));
  assert.equal(chatCalls,1);
  assert.match(messages.at(-1).children[1].textContent,expected);
  assert.equal(nodes.get('#command-form button[type="submit"]').disabled,false);
  assert.equal(vm.runInContext('isProcessing',context),false);
  assert.ok(![...timers.values()].some(t=>t.ms===120000));
}
(async()=>{
 await scenario({ok:true,body:'{"response":"Hello from JARVIS"}'},/Hello from JARVIS/);
 await scenario({ok:false,body:'{"detail":"Ollama unavailable"}'},/Ollama unavailable/);
 await scenario({ok:false,body:'Internal Server Error'},/unreadable reply/);
 await scenario({ok:true,body:'{"response":""}'},/empty reply/);
 await scenario({},/Network unavailable/,true);
 console.log('PASS: success, API failure, non-JSON failure, empty reply, network failure; composer recovers after each.');
})().catch(e=>{console.error(e);process.exitCode=1;});
