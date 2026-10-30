# 共用小工具：開頁面、擋外部網路、假 Firebase、假語音（記下唸了什麼）
import os, json
from playwright.sync_api import sync_playwright
HTML = 'file://' + os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'index.html'))
SETTINGS_KEY = 'hanziGames.settings'
APP = "export function initializeApp(c,n){return {c,n}}"
FS = '''
const DB=(window.__db=window.__db||{});
const op=(k,p,d)=>(window.__ops=window.__ops||[]).push({k,p,d});
export function getFirestore(app){return {app}}
export function initializeFirestore(app){return {app}}
export const collection=(db,...p)=>({db,path:p.join('/')});
export const doc=(db,...p)=>({db,path:p.join('/')});
export const serverTimestamp=()=>'SERVER_TS';
export async function setDoc(r,d){ op('set',r.path,d); DB[r.path]=JSON.parse(JSON.stringify(d)); }
export async function addDoc(c,d){op('add',c.path,d);return {id:'P'+(window.__ops.length)}}
export async function updateDoc(r,d){op('update',r.path,d)}
export const getDoc=async(r)=>({exists:()=>r.path in DB,data:()=>DB[r.path]});
export const getDocs=async(q)=>{const c=q[0].path;const rows=Object.keys(DB).filter(k=>k.startsWith(c+'/')).map(k=>DB[k]).sort((a,b)=>b.score-a.score);const n=q[2]||999;const l=rows.slice(0,n);return {docs:l.map(d=>({data:()=>d})),size:l.length,forEach(){}}};
export const query=(...a)=>a,where=()=>0,orderBy=()=>0,limit=(n)=>n,onSnapshot=()=>()=>{},deleteDoc=async(r)=>{op("delete",r.path);delete DB[r.path]},increment=()=>0,runTransaction=async()=>{},writeBatch=()=>({}),Timestamp={now:()=>({}),fromDate:()=>({}),fromMillis:(m)=>({ms:m})},arrayUnion=()=>0,startAfter=()=>0,getCountFromServer=async()=>({data:()=>({count:0})}),documentId=()=>'id',enableIndexedDbPersistence=async()=>{};
'''
AUTH = """const a={currentUser:null,authStateReady:async()=>{}};
export const getAuth=()=>a,GoogleAuthProvider=class{};
export const signInAnonymously=async()=>{a.currentUser={uid:(window.__uid||'UID1'),isAnonymous:true};return {user:a.currentUser}};
export const onAuthStateChanged=(x,cb)=>{setTimeout(()=>cb(a.currentUser),0);return()=>{}};
export const signInWithPopup=async()=>{},signOut=async()=>{},signInWithCredential=async()=>{},setPersistence=async()=>{},browserLocalPersistence={};"""
FAKE_SPEECH = """(() => {
  window.__spoken = [];
  const voices = [{lang:'zh-TW', name:'Fake', default:true, localService:true, voiceURI:'fake'}];
  const synth = { getVoices: () => voices, speak: u => window.__spoken.push({text:u.text, rate:u.rate, lang:u.lang}),
                  cancel(){}, pause(){}, resume(){}, addEventListener(){}, removeEventListener(){}, speaking:false, pending:false, paused:false };
  Object.defineProperty(window, 'speechSynthesis', {value: synth, configurable:true});
  window.SpeechSynthesisUtterance = function(t){ this.text = t; this.rate = 1; this.lang = ''; };
})();"""

def route(r):
    u = r.request.url
    if u.startswith('file:'): return r.continue_()
    if 'gstatic.com/firebasejs' in u:
        if 'compat' in u: return r.fulfill(status=200, content_type='application/javascript', body='')
        body = APP if 'firebase-app' in u else FS if 'firestore' in u else AUTH if 'auth' in u else ''
        return r.fulfill(status=200, content_type='application/javascript', body=body)
    r.abort()

class Runner:
    def __init__(self): self.fails = 0
    def check(self, cond, msg):
        print(('  ok  ' if cond else '  FAIL'), msg)
        if not cond: self.fails += 1

def open_page(p, query='', settings=None, width=390, height=800, wait=1200, extra_init=None):
    b = p.chromium.launch(args=['--no-sandbox'])
    ctx = b.new_context(viewport={'width': width, 'height': height})
    ctx.add_init_script(FAKE_SPEECH)
    if settings is not None:
        ctx.add_init_script("try{localStorage.setItem(%s,%s)}catch(e){}" % (json.dumps(SETTINGS_KEY), json.dumps(json.dumps(settings))))
    if extra_init: ctx.add_init_script(extra_init)
    pg = ctx.new_page()
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)[:150]))
    ctx.route('**/*', route)
    pg.goto(HTML + query); pg.wait_for_timeout(wait)
    return b, pg, errs
