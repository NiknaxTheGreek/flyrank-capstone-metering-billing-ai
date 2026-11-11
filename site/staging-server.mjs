import http from 'node:http';
import { createHmac, randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('./dist/', import.meta.url)));
const COOKIE = '__Host-bosnia-staging';
const MAX_AGE = 12 * 60 * 60;
const key = Buffer.from(process.env.STAGING_SESSION_SECRET || '', 'hex');
const salt = process.env.STAGING_PASSWORD_SALT || '';
const stored = Buffer.from(process.env.STAGING_PASSWORD_HASH || '', 'hex');
const configured = key.length === 32 && /^[a-f0-9]{32,128}$/i.test(salt) && stored.length === 64;
const attempts = new Map();
const mime = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8',
  '.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8',
  '.json':'application/json','.svg':'image/svg+xml','.png':'image/png',
  '.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp',
  '.ico':'image/x-icon','.woff':'font/woff','.woff2':'font/woff2',
  '.pdf':'application/pdf','.csv':'text/csv; charset=utf-8',
  '.wasm':'application/wasm','.txt':'text/plain; charset=utf-8'};
const security = {'Cache-Control':'no-store','X-Robots-Tag':'noindex, nofollow, noarchive',
  'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'};
const loginPolicy = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";

function send(res,status,body,headers={}) {
  res.writeHead(status,{...security,...headers});
  res.end(body);
}
function signature(payload) {
  return createHmac('sha256',key).update(payload).digest('base64url');
}
function issueSession() {
  const payload = Buffer.from(JSON.stringify({
    exp:Date.now()+MAX_AGE*1000, nonce:randomBytes(16).toString('hex')
  })).toString('base64url');
  return payload+'.'+signature(payload);
}
function authenticated(req) {
  const token = (req.headers.cookie || '').split(';').map(x=>x.trim())
    .find(x=>x.startsWith(COOKIE+'='))?.slice(COOKIE.length+1);
  if (!token || token.length > 1024) return false;
  const parts = token.split('.');
  if (parts.length !== 2 || !parts.every(x=>/^[A-Za-z0-9_-]+$/.test(x))) return false;
  const actual=Buffer.from(parts[1],'base64url');
  const expected=Buffer.from(signature(parts[0]),'base64url');
  if(actual.length !== expected.length || !timingSafeEqual(actual,expected)) return false;
  try {
    const info=JSON.parse(Buffer.from(parts[0],'base64url').toString('utf8'));
    return Number.isSafeInteger(info.exp) && info.exp>Date.now()
      && info.exp<=Date.now()+MAX_AGE*1000 && /^[a-f0-9]{32}$/.test(info.nonce);
  } catch { return false; }
}
function loginPage(bad=false) {
  return '<!doctype html><html lang="en"><head><meta charset="utf-8">'+
    '<meta name="viewport" content="width=device-width,initial-scale=1">'+
    '<meta name="robots" content="noindex,nofollow"><title>Private Portfolio Preview</title>'+
    '<style>*,*:before,*:after{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;'+
    'place-items:center;padding:24px;background:#071827;color:#f0f7ff;font:16px system-ui,sans-serif}'+
    'main{width:min(100%,400px);border:1px solid #2e5363;background:#10283a;padding:32px;'+
    'border-radius:16px;box-shadow:0 20px 70px #0006}h1{margin:0 0 8px;font-size:24px}'+
    'p{color:#bed2df;line-height:1.5}label{display:block;margin:24px 0 8px}'+
    'input,button{font:inherit;width:100%;padding:12px 14px;border-radius:8px}'+
    'input{background:#071827;border:1px solid #7295a5;color:white}button{margin-top:14px;'+
    'border:0;background:#17b7c9;color:#08232b;font-weight:700;cursor:pointer}'+
    '.err{color:#ffacb2}small{display:block;margin-top:20px;color:#a9bdcb}</style></head><body><main>'+
    '<h1>Private Portfolio Preview</h1><p>Development staging for the interactive BI portfolio and '+ 
    'Maths &amp; Physics tutoring lab.</p>'+
    (bad?'<p class="err" role="alert">Incorrect password. Please try again later.</p>':'')+
    '<form method="post" action="/__staging/login"><label for="password">Preview password</label>'+
    '<input id="password" name="password" type="password" required autocomplete="current-password" autofocus>'+
    '<button type="submit">Unlock staging</button></form>'+
    '<small>This preview is not the public portfolio.</small></main></body></html>';
}
function allowedAttempt(req) {
  const now=Date.now(), ip=req.socket.remoteAddress||'unknown';
  if(attempts.size>300) attempts.clear();
  const prev=attempts.get(ip);
  if(!prev || prev.until<now){attempts.set(ip,{count:1,until:now+15*60_000});return true;}
  if(prev.count>=8) return false;
  prev.count++; return true;
}
function handleLogin(req,res) {
  if(!allowedAttempt(req)) return send(res,429,'Too many attempts; retry later.',
    {'Content-Type':'text/plain; charset=utf-8','Retry-After':'900'});
  if(!req.headers['content-type']?.startsWith('application/x-www-form-urlencoded'))
    return send(res,415,'Unsupported content type');
  let body='',finished=false;
  req.on('data',chunk=>{
    if(finished)return;
    body+=chunk;
    if(body.length>4096){finished=true;send(res,413,'Request too large');}
  });
  req.on('end',()=>{
    if(finished)return;
    const pass=new URLSearchParams(body).get('password')||'';
    if(pass.length>256)return send(res,400,'Invalid request');
    const hash=scryptSync(pass,salt,64);
    if(timingSafeEqual(hash,stored)) {
      const cookie=COOKIE+'='+issueSession()+'; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age='+MAX_AGE;
      return send(res,303,'',{'Location':'/','Set-Cookie':cookie});
    }
    send(res,401,loginPage(true),{'Content-Type':'text/html; charset=utf-8',
      'Content-Security-Policy':loginPolicy});
  });
  req.on('error',()=>{if(!finished)send(res,400,'Invalid request');});
}
async function serveFile(pathname,req,res) {
  let rel;
  try {rel=decodeURIComponent(pathname);} catch{return send(res,400,'Bad path');}
  if(rel.includes('\\')||rel.includes('\0'))return send(res,400,'Bad path');
  const dest=rel.endsWith('/')?rel+'index.html':extname(rel)?rel:rel+'/index.html';
  const file=resolve(ROOT,'.'+dest);
  if(!file.startsWith(ROOT+sep))return send(res,403,'Forbidden');
  let info;
  try {info=await stat(file);} catch{return send(res,404,'Not found');}
  if(!info.isFile())return send(res,404,'Not found');
  res.writeHead(200,{...security,'Cache-Control':'private, no-store',
    'Content-Length':info.size,'Content-Type':mime[extname(file).toLowerCase()]||'application/octet-stream'});
  if(req.method==='HEAD')return res.end();
  const stream=createReadStream(file);
  stream.on('error',()=>res.destroy());
  stream.pipe(res);
}
http.createServer((req,res)=>{
  if(!configured)return send(res,503,'Staging authentication is not configured. Access denied.');
  let path;
  try {path=new URL(req.url,'http://localhost').pathname;}catch{return send(res,400,'Bad request');}
  if(path==='/__staging/login'&&req.method==='POST')return handleLogin(req,res);
  if(path==='/__staging/login'&&req.method==='GET'){
    if(authenticated(req))return send(res,303,'',{'Location':'/'});
    return send(res,200,loginPage(),{'Content-Type':'text/html; charset=utf-8',
      'Content-Security-Policy':loginPolicy});
  }
  if(path==='/__staging/logout'&&req.method==='POST')
    return send(res,303,'',{'Location':'/__staging/login',
      'Set-Cookie':COOKIE+'=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0'});
  if(req.method!=='GET'&&req.method!=='HEAD')return send(res,405,'Method not allowed');
  if(!authenticated(req))return send(res,303,'',{'Location':'/__staging/login'});
  if(path.startsWith('/__staging/'))return send(res,404,'Not found');
  void serveFile(path,req,res).catch(()=>{
    if(!res.headersSent)send(res,500,'Server error');else res.destroy();
  });
}).listen(Number(process.env.PORT)||3000,'0.0.0.0',()=>{
  console.log('Private staging server started');
});
