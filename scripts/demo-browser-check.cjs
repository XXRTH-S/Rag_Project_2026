// Read secrets in memory only; do not record login request bodies or storage state.
const fs = require("fs");
const path = require("path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(__dirname, "..");
const env = Object.fromEntries(fs.readFileSync(path.join(root,".env"),"utf8").split(/\r?\n/).filter(l=>/^[A-Z0-9_]+=/.test(l)).map(l=>{const i=l.indexOf("=");return [l.slice(0,i),l.slice(i+1).replace(/^"|"$/g,"")]}));
const base=process.env.DEMO_TEST_URL || "http://localhost";
const api=process.env.DEMO_TEST_API || "http://localhost:8000";
const out=path.join(root,"output/playwright");
fs.mkdirSync(out,{recursive:true});
function apiGet(ctx,url){return ctx.request.get(url,{headers:{"ngrok-skip-browser-warning":"1"}})}
function check(ok,why){if(!ok)throw new Error(why)}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:"msedge"});
 const records=[];const contexts=[];const errors=[];
 try {
  for(let i=1;i<=5;i++){
   const ctx=await browser.newContext({viewport:i===5?{width:390,height:844}:{width:1440,height:900}});contexts.push(ctx);
   const page=await ctx.newPage();page.on("pageerror",e=>errors.push(e.message));
   await page.goto(base+"/login");await page.waitForLoadState("networkidle");
   check(await page.locator("#email").count()===1,"Login form unavailable");
   await page.locator("#email").fill(env[`DEMO_USER_${i}_EMAIL`]);
   await page.locator("#password").fill(env[`DEMO_USER_${i}_PASSWORD`]);
   await page.locator("button[type=submit]").click();await page.waitForURL("**/documents");await page.locator("tbody tr").first().waitFor();
   const docsResponse=await apiGet(ctx,api+"/api/documents");check(docsResponse.ok(),"Documents request failed");
   const docs=await docsResponse.json();check(docs.items.length===1&&docs.items[0].filename===`demo-${String(i).padStart(2,"0")}-guide.md`,"Unexpected documents for demo account "+i);
   const quota=await (await apiGet(ctx,api+"/api/me/quota")).json();check(quota.documents.limit===5&&quota.pages.limit===500,"Wrong quota for "+i);
   check((await apiGet(ctx,api+"/api/admin/users")).status()===403,"Admin API exposed");
   check(await page.getByRole("link",{name:"จัดการผู้ใช้",exact:true}).count()===0,"Admin menu visible");
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Page overflow");
   await page.screenshot({path:path.join(out,`demo-${i}-documents.png`),fullPage:true});
   records.push({account:i,login:true,ownDocument:docs.items[0].id,quota:{documents:quota.documents.limit,pages:quota.pages.limit},adminBlocked:true});
  }
  let isolation=0;
  for(let i=0;i<5;i++)for(let j=0;j<5;j++)if(i!==j){
   check((await apiGet(contexts[i],api+"/api/documents/"+records[j].ownDocument)).status()===404,"Cross-account document leak");isolation++;
  }
  const page=contexts[0].pages()[0];await page.goto(base+"/chat");await page.waitForLoadState("networkidle");
  const question=page.getByRole("textbox",{name:"คำถามถึงผู้ช่วย"});await question.fill("โครงการตัวอย่างของบัญชีนี้ชื่ออะไร");await page.locator(".composer button[type=submit]").click();
  await page.locator(".msg.assistant .btn").first().waitFor({timeout:150000});
  check((await page.locator(".msg.assistant").last().innerText()).length>10,"Empty chat answer");
  await page.screenshot({path:path.join(out,"demo-chat.png"),fullPage:true});
  const anonymous=await browser.newContext();const wrong=await anonymous.request.post(api+"/api/auth/login",{data:{email:env.DEMO_USER_1_EMAIL,password:"definitely-wrong-password"}});check(wrong.status()===401,"Wrong password accepted");await anonymous.close();
  const result={accounts:records.map(({ownDocument,...r})=>r),crossAccountDenials:isolation,chatCompleted:true,wrongPasswordRejected:true,errors};
  check(errors.length===0,"Browser errors encountered");fs.writeFileSync(path.join(out,"demo-results.json"),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 } finally {await browser.close()}
})().catch(e=>{console.error(e.message);process.exit(1)});
