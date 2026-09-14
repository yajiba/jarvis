// Optional real-browser check: npm.cmd install --prefix data/browser-check playwright
const {chromium}=require('../data/browser-check/node_modules/playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'no-preference'});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 let pending=[{id:'test-approval',tool:'schedule_project_command',details:{project:'demo',command:'check',due_at:'2026-09-15T08:00:00+08:00'}}];
 let decision=null;
 await page.route('http://127.0.0.1:9876/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync('jarvis/api/ui/index.html')});
  if(url.pathname.startsWith('/ui/'))return route.fulfill({contentType:'image/png',body:fs.readFileSync('jarvis/api/ui/'+url.pathname.split('/').pop())});
  if(url.pathname==='/approvals/test-approval'){decision=route.request().postDataJSON();pending=[];return route.fulfill({json:{status:'answered'}});}
  const responses={
   '/approvals':pending,'/automations':{jobs:[],events:[]},'/memory':{tasks:[],memories:[]},
   '/runtime':{connection:'ready',model:'qwen3:8b',voice:'amy',engine:'Piper',voice_enabled:true},
   '/status':{hardware:{},model:'qwen3:8b'},'/activity':{state:'Ready'}
  };
  return route.fulfill({json:responses[url.pathname]||{}});
 });
 await page.goto('http://127.0.0.1:9876/');
 await page.waitForFunction(()=>document.querySelector('#approval-panel').hidden===false);
 await page.getByRole('button',{name:'Allow',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('#approval-panel').hidden);
 assert.deepEqual(decision,{approved:true});
 assert.equal(await page.locator('.avatar').count(),1);
 assert.equal(await page.locator('.avatar .avatar-body').getAttribute('src'),'/ui/portrait-clean.png?v=3');
 await page.evaluate(()=>{micEnabled=false;releaseMic();speaking=true;setMouth(.9);});
 assert.equal(await page.locator('#avatar').getAttribute('data-mouth'),'wide');
 assert.equal(await page.locator('.avatar img').count(),1);
 assert.ok(await page.locator('.avatar-body').evaluate(node=>node.complete && node.naturalWidth>0));
 await page.waitForTimeout(500);console.log(await page.evaluate(()=>({mouth:document.querySelector('#avatar').dataset.mouth,opacity:getComputedStyle(document.querySelector('.talk-mouth')).opacity,motion:matchMedia('(prefers-reduced-motion: reduce)').matches,micEnabled,listening,micStarting})));
 assert.equal(await page.locator('.talk-mouth').evaluate(node=>getComputedStyle(node).opacity),'1');
 assert.match(await page.locator('.talk-lower').evaluate(node=>getComputedStyle(node).transform),/15/);
 await page.locator('.avatar-blink').evaluate(node=>{const animation=node.getAnimations()[0];animation.pause();animation.currentTime=5000;});
 assert.equal(await page.locator('.avatar-blink').evaluate(node=>getComputedStyle(node).opacity),'1');
 await page.locator('.face-stage').screenshot({path:'data/avatar-speaking-blink.png'});
 await page.locator('.avatar-blink').evaluate(node=>{node.getAnimations()[0].currentTime=0;});
 await page.evaluate(()=>{setMouth(0);});
 assert.equal(await page.locator('.talk-mouth').evaluate(node=>getComputedStyle(node).opacity),'0');
 await page.evaluate(()=>stopVoice());
 assert.equal(await page.locator('#avatar').getAttribute('data-mouth'),'rest');
 await page.screenshot({path:'data/avatar-dashboard-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'data/avatar-dashboard-mobile.png',fullPage:true});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'No horizontal overflow on mobile');
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.evaluate(()=>{micEnabled=false;releaseMic();speaking=true;setMouth(.9);});
 assert.equal(await page.locator('.talk-mouth').evaluate(node=>getComputedStyle(node).opacity),'0');
 assert.equal(await page.locator('.avatar-blink').evaluate(node=>getComputedStyle(node).opacity),'0');
 assert.deepEqual(errors,[]);
 console.log('PASS: browser avatar, mouth reset, explicit approval, mobile layout, no JavaScript errors.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
