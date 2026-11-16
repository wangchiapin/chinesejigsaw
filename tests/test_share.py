# 文字拼圖：分享成績鈕＋ ?ref=share 記號測試（假 Firebase 記錄 visits／plays 寫入）
# 用法：python3 tests/test_share.py
import sys, os, re, json
from playwright.sync_api import sync_playwright
import common
from common import *

R = Runner()
URL = 'https://wangchiapin.github.io/chinesejigsaw/?ref=share'
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, '..', 'index.html'), encoding='utf-8').read()
HOOK = ("window.__jig={get G(){return G},get lastResult(){return lastResult},settings:settings,checkWin:()=>checkWin()};\n  function checkWin() {")
assert SRC.count('  function checkWin() {') == 1
PATCHED = SRC.replace('  function checkWin() {', HOOK, 1)
_src = open(os.path.join(HERE, 'test_game.py'), encoding='utf-8').read()
FAKE_FB = re.search(r'FAKE_FB = r"""(.*?)"""', _src, re.S).group(1)   # 排行榜用的舊版 Firebase 替身，沿用拼圖測試的

def route(r):
    u = r.request.url
    if u.startswith('file:'):
        if u.split('?')[0].endswith('/index.html'):
            return r.fulfill(status=200, content_type='text/html; charset=utf-8', body=PATCHED)
        return r.continue_()
    if 'gstatic.com/firebasejs' in u:
        if 'compat' in u: return r.fulfill(status=200, content_type='application/javascript', body=FAKE_FB if 'firebase-app-compat' in u else '')
        body = common.APP if 'firebase-app' in u else common.FS if 'firestore' in u else common.AUTH if 'auth' in u else ''
        return r.fulfill(status=200, content_type='application/javascript', body=body)
    r.abort()
common.route = route

def stubs(share='ok', clip='ok'):
    s = "window.confirm=()=>true;window.__shared=[];window.__copied=[];"
    if share == 'none': s += "try{Object.defineProperty(navigator,'share',{value:undefined,configurable:true});}catch(e){}"
    else:
        body = "window.__shared.push(d);"
        if share == 'abort': body += "const e=new Error('x');e.name='AbortError';throw e;"
        if share == 'hang': body += "await new Promise(r=>setTimeout(r,600));"
        s += "navigator.share=async d=>{%s};" % body
    s += "document.execCommand=()=>%s;" % ('false' if clip == 'fail' else 'true')
    s += "try{Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>{%s}},configurable:true});}catch(e){}" % ("throw new Error('no')" if clip == 'fail' else "window.__copied.push(t)")
    return s

def page(p, settings=None, query='', share='ok', clip='ok', wait=1800):
    return open_page(p, query=query, settings=settings, wait=wait, extra_init=stubs(share, clip), width=1000, height=800)

def J(pg, expr, arg=None): return pg.evaluate("a=>{const J=window.__jig;%s}" % expr, arg)
def to_win(pg, name='Ana', moves=64, secs=75):
    pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(700)
    J(pg, """const G=J.G;G.pieces.forEach(p=>{p.pool=false;p.g=0;p.rot=0;p.x=G.fx+p.c*G.P;p.y=G.fy+p.r*G.P});
      G.moves=a[0];G.start=performance.now()-a[1]*1000;""", [moves, secs])
    if name is not None: pg.evaluate("n=>{try{localStorage.setItem('jigsaw_name',n)}catch(e){}}", name)
    J(pg, "J.checkWin()"); pg.wait_for_timeout(1000)

txt = lambda pg, sel: ' '.join(pg.inner_text(sel).split())
shared = lambda pg: pg.evaluate("window.__shared")
ops = lambda pg: pg.evaluate("window.__ops||[]")
base = {'v': 1, 'script': 'trad', 'lang': 'es', 'phon': 'off', 'rate': 'normal'}

with sync_playwright() as p:
    print('完成畫面的分享鈕')
    b, pg, errs = page(p, settings=base)
    to_win(pg)
    R.check(pg.is_visible('#win'), '拼完跳出完成畫面')
    order = pg.evaluate("[...document.querySelectorAll('#win .card > button')].map(b=>b.id)")
    R.check(order == ['winRank', 'winAgain', 'winShare', 'winClose'], '分享鈕在「再玩一次」之後、「看看成品」之前 %s' % order)
    R.check(pg.is_visible('#winShare'), '顯示分享鈕')
    R.check('分享成績' in txt(pg, '#winShare') and 'Compartir resultado' in txt(pg, '#winShare'), '中文＋西文小字：' + txt(pg, '#winShare'))
    st = pg.evaluate("(()=>{const c=getComputedStyle(document.getElementById('winShare'));return [c.backgroundColor,parseFloat(c.borderTopWidth)]})()")
    R.check(st[1] >= 2 and st[0] == 'rgb(255, 255, 255)', '空心外框樣式 %s' % st)
    R.check('winShare' != 'btn-restart', '沒有用 .btn-restart')
    pg.click('#winShare'); pg.wait_for_timeout(200)
    s = shared(pg)
    R.check(len(s) == 1, '呼叫系統分享選單一次')
    R.check(s and s[0]['url'] == URL, '連結＝公開頁＋?ref=share：%s' % (s and s[0]['url']))
    R.check(s and s[0]['text'].startswith('Ana completó un rompecabezas de 64 piezas') and '01:1' in s[0]['text'] and ' 64 movimientos' in s[0]['text'] and 'Rompecabezas de chino' in s[0]['text'], '西文句子含暱稱、片數、時間、移動：%s' % (s and s[0]['text']))
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()

    print('沒暱稱／語言／字體')
    b, pg, errs = page(p, settings=base)
    to_win(pg, name='')
    pg.click('#winShare'); pg.wait_for_timeout(200); s = shared(pg)
    R.check(s and s[0]['text'].startswith('¡Completé un rompecabezas de 64 piezas') and s[0]['text'].count('!') == 1, '西文沒暱稱：%s' % (s and s[0]['text']))
    b.close()
    b, pg, errs = page(p, settings=dict(base, lang='en')); to_win(pg, name='Bo')
    R.check('Share result' in txt(pg, '#winShare'), '英文介面：Share result')
    pg.click('#winShare'); pg.wait_for_timeout(200); s = shared(pg)
    R.check(s and s[0]['text'].startswith('Bo finished a 64-piece puzzle in "Chinese Jigsaw Puzzle"') and ' 64 moves' in s[0]['text'], '英文句子：%s' % (s and s[0]['text']))
    b.close()
    b, pg, errs = page(p, settings=dict(base, lang='zh')); to_win(pg, name='')
    R.check(txt(pg, '#winShare') == '分享成績', '繁體純中文：分享成績：' + txt(pg, '#winShare'))
    pg.click('#winShare'); pg.wait_for_timeout(200); s = shared(pg)
    R.check(s and s[0]['text'].startswith('我在「文字拼圖」用 ') and '拼好了 64 片的拼圖' in s[0]['text'] and s[0]['title'].startswith('文字拼圖'), '繁體句子，沒暱稱用「我」：%s' % (s and s[0]['text']))
    b.close()
    b, pg, errs = page(p, settings=dict(base, lang='zh', script='simp')); to_win(pg, name='小明')
    R.check(txt(pg, '#winShare') == '分享成绩', '简体：分享成绩：' + txt(pg, '#winShare'))
    pg.click('#winShare'); pg.wait_for_timeout(200); s = shared(pg)
    R.check(s and s[0]['text'].startswith('小明在「文字拼图」用 ') and '拼图' in s[0]['text'] and '拼圖' not in s[0]['text'] and s[0]['title'].startswith('文字拼图'), '简体句子與標題：%s' % [s and (s[0]['text'], s[0]['title'])])
    b.close()
    b, pg, errs = page(p, settings=dict(base, lang='es', script='simp')); to_win(pg, name='')
    pg.click('#winShare'); pg.wait_for_timeout(200); s = shared(pg)
    R.check(s and s[0]['title'].startswith('文字拼图'), '西文＋简体：標題中文名用简体：%s' % (s and s[0]['title']))
    b.close()

    print('分享選單的各種結果')
    b, pg, errs = page(p, settings=base, share='abort'); to_win(pg); before = txt(pg, '#winShare')
    pg.click('#winShare'); pg.wait_for_timeout(200)
    R.check(txt(pg, '#winShare') == before and pg.evaluate("window.__copied") == [], '玩家關掉選單：文字不變、不複製')
    b.close()
    b, pg, errs = page(p, settings=base, share='none'); to_win(pg)
    pg.click('#winShare'); pg.wait_for_timeout(250)
    cp = pg.evaluate("window.__copied")
    R.check(len(cp) == 1 and cp[0].endswith('\n' + URL), '不支援分享選單：複製「句子＋連結」')
    R.check('已複製' in txt(pg, '#winShare'), '按鈕顯示已複製')
    pg.wait_for_timeout(2500)
    R.check('分享成績' in txt(pg, '#winShare'), '約 2 秒後文字恢復')
    b.close()
    b, pg, errs = page(p, settings=base, share='none', clip='fail'); to_win(pg)
    pg.click('#winShare'); pg.wait_for_timeout(250)
    R.check('複製失敗' in txt(pg, '#winShare'), '連複製也失敗：顯示複製失敗')
    b.close()
    b, pg, errs = page(p, settings=base, share='hang'); to_win(pg)
    pg.evaluate("document.getElementById('winShare').click();document.getElementById('winShare').click()"); pg.wait_for_timeout(900)
    R.check(len(shared(pg)) == 1, '連點兩下只分享一次')
    b.close()

    print('再玩一次後完成畫面關閉')
    b, pg, errs = page(p, settings=base); to_win(pg)
    pg.click('#winAgain'); pg.wait_for_timeout(800)
    R.check(not pg.is_visible('#win'), '按「再玩一次」：完成畫面關閉（分享鈕跟著消失）')
    b.close()

    print('?ref=share 記號')
    def refcase(query, label, expect):
        b, pg, errs = page(p, settings=base, query=query, wait=3200)
        pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(700)
        o = [x for x in ops(pg) if x['p'].startswith('visits/') or (x['k'] == 'add' and x['p'] == 'plays')]
        R.check(len(o) >= 2 and all((x['d'].get('ref') == expect) if expect else ('ref' not in x['d']) for x in o), '%s %s' % (label, o))
        if expect: R.check(pg.evaluate("sessionStorage.getItem('hg.ref')") == expect, '記號暫存在 sessionStorage')
        b.close()
    refcase('?ref=share', '帶 ?ref=share：visits／plays 都有 ref=share', 'share')
    refcase('?ref=SHARE', '大小寫轉小寫', 'share')
    refcase('', '沒帶：不寫 ref', None)
    refcase('?ref=%3Cscript%3E', '不合規的記號不寫入', None)

print('FAILS', R.fails); sys.exit(1 if R.fails else 0)
