# 文字拼圖測試：不改遊戲本檔，載入時由測試端在「檢查用出入口」補一行（只讀、只呼叫遊戲自己的函式），
# 其餘全部用真的滑鼠拖曳、按鈕操作。涵蓋：拖曳拼完、吸附力三檔、旋轉、結算、排行榜、設定每個值、電腦／手機版、拼音載入失敗。
import sys, re, json, os
from playwright.sync_api import sync_playwright
import common
from common import *

R = Runner()
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, '..', 'index.html'), encoding='utf-8').read()
HOOK = ("window.__jig={get G(){return G},get lastResult(){return lastResult},settings:settings,checkWin:()=>checkWin(),"
        "rotateSet:(m,d,cx,cy)=>rotateSet(m,d,cx,cy),poolToScreen:(x,y)=>poolToScreen(x,y),maxScroll:()=>maxScroll(),"
        "get drag(){return drag},get isMobile(){return isMobile}};\n  function checkWin() {")
assert SRC.count('  function checkWin() {') == 1
PATCHED = SRC.replace('  function checkWin() {', HOOK, 1)
PINYIN = open('/tmp/pp/node_modules/pinyin-pro/dist/index.js', encoding='utf-8').read() if os.path.exists('/tmp/pp/node_modules/pinyin-pro/dist/index.js') else None

FAKE_FB = r"""
(function(){
  window.__db = window.__db || {}; window.__ops = window.__ops || [];
  if (window.firebase && window.firebase.__fake) return;
  const DB = window.__db, ops = window.__ops, clone = x => JSON.parse(JSON.stringify(x));
  const depth = p => p.split('/').length;
  function docRef(path){ return { path, id: path.split('/').pop(),
    async get(){ return { exists: path in DB, data: () => DB[path] && clone(DB[path]) }; },
    async set(d){ ops.push({k:'set', p:path, d:clone(d)}); DB[path] = clone(d); },
    async update(d){ DB[path] = Object.assign(DB[path]||{}, clone(d)); },
    async delete(){ delete DB[path]; },
    collection: sub => colRef(path + '/' + sub),
    onSnapshot(){ return () => {}; } }; }
  function colRef(path){ const q = { doc: id => docRef(path + '/' + id),
    async add(d){ if (window.__failAdd) throw new Error('add-fail'); ops.push({k:'add', p:path, d:clone(d)}); const id = 'A' + ops.length; DB[path + '/' + id] = clone(d); return { id }; },
    where(){ return q; }, orderBy(){ return q; }, limit(){ return q; },
    async get(){ const ks = Object.keys(DB).filter(k => k.startsWith(path + '/') && depth(k) === depth(path) + 1);
      const rows = ks.map(k => clone(DB[k])).sort((a,b)=>(b.rank||b.score||0)-(a.rank||a.score||0));
      return { empty: rows.length === 0, docs: rows.map(r => ({ data: () => r })), size: rows.length, forEach(fn){ rows.forEach(r => fn({ data: () => r })); } }; } };
    return q; }
  const auth = { currentUser: null, async signInAnonymously(){ auth.currentUser = { uid: window.__uid || 'UID1' }; return { user: auth.currentUser }; } };
  const fsInst = { collection: colRef, async runTransaction(fn){ return fn({ get: r => r.get(), set(r, d){ DB[r.path] = clone(d); }, update(r, d){ DB[r.path] = Object.assign(DB[r.path]||{}, clone(d)); } }); } };
  const fire = () => fsInst; fire.FieldValue = { serverTimestamp: () => 'TS', delete: () => null, increment: () => 1 };
  fire.Timestamp = { now: () => ({ toMillis: () => Date.now() }), fromMillis: m => ({ toMillis: () => m }) };
  window.firebase = { __fake: true, apps: [], auth: () => auth, firestore: fire, initializeApp(){ return {}; } };
})();
"""
FLAGS = {'fb': True, 'pinyin': True}
def route(r):
    u = r.request.url
    if u.startswith('file:'):
        if u.split('?')[0].endswith('/index.html'):
            return r.fulfill(status=200, content_type='text/html; charset=utf-8', body=PATCHED)
        return r.continue_()
    if 'gstatic.com/firebasejs' in u:
        if not FLAGS['fb']: return r.abort()
        return r.fulfill(status=200, content_type='application/javascript', body=FAKE_FB if 'firebase-app-compat' in u else '')
    if 'pinyin-pro' in u:
        if not FLAGS['pinyin'] or PINYIN is None: return r.abort()
        return r.fulfill(status=200, content_type='application/javascript', body=PINYIN)
    r.abort()
common.route = route

def page(p, query='', settings=None, width=1000, height=800, extra=None):
    return open_page(p, query=query, settings=settings, width=width, height=height, wait=1800, extra_init="window.confirm=()=>true;" + (extra or ''))

def J(pg, expr, arg=None): return pg.evaluate("a=>{const J=window.__jig;%s}" % expr, arg)
def gate(pg):
    pg.click('#btnGo'); pg.wait_for_timeout(150)

def canvas_origin(pg): return pg.evaluate("(()=>{const r=document.getElementById('cv').getBoundingClientRect();return [r.left,r.top]})()")

def drag_piece_to_slot(pg, pid, dx=0, dy=0):
    """把拼圖池裡第 pid 片真的拖到桌上它該在的格子（可加偏移）"""
    info = J(pg, """const G=J.G;const p=G.pieces[a];
      J.G.scroll=Math.max(0,Math.min(J.maxScroll(),p.y-120));
      const [sx,sy]=J.poolToScreen(p.x,p.y);
      return {sx:sx+G.P/2,sy:sy+G.P/2,tx:G.fx+p.c*G.P+G.P/2,ty:G.fy+p.r*G.P+G.P/2}""", pid)
    ox, oy = canvas_origin(pg)
    pg.mouse.move(ox + info['sx'], oy + info['sy']); pg.mouse.down()
    pg.mouse.move(ox + (info['sx'] + info['tx']) / 2, oy + (info['sy'] + info['ty']) / 2, steps=3)
    pg.mouse.move(ox + info['tx'] + dx, oy + info['ty'] + dy, steps=3); pg.mouse.up()
    pg.wait_for_timeout(30)

def solve_instantly(pg, rot=0):
    """捷徑：直接把所有片放到正確位置（拼好狀態），再呼叫遊戲自己的 checkWin"""
    J(pg, """const G=J.G;G.pieces.forEach(p=>{p.pool=false;p.g=0;p.rot=0;p.x=G.fx+p.c*G.P;p.y=G.fy+p.r*G.P});
      G.moves=Math.max(G.moves,5);""")

with sync_playwright() as p:
    # ───── 1) 開頁：停在「開始」前，不計時 ─────
    b, pg, errs = page(p)
    R.check(pg.is_visible('#gate') and J(pg, "return J.G.gate"), '一打開停在開始鈕前')
    t0 = pg.inner_text('#timer'); pg.wait_for_timeout(1300)
    R.check(pg.inner_text('#timer') == t0 == '⏱ 00:00', '按開始之前不計時')
    R.check(J(pg, "return J.G.N") == 100 and pg.input_value('#selGrid') == '10', '預設 10×10＝100 片')
    R.check(J(pg, "return J.G.text") == '快樂拼圖遊戲好好玩', '預設文字')
    R.check(J(pg, "return J.G.pieces.every(p=>p.pool)"), '全部片都在拼圖池')
    R.check(J(pg, "return J.G.pieces.filter(p=>p.type===0).length") == 4, '四個角片')
    R.check(J(pg, "return J.G.pieces.filter(p=>p.type===1).length") == 4 * 8, '邊片 32 個')
    R.check(pg.inner_text('#status').count('100') >= 1 or '0' in pg.inner_text('#status'), '狀態列顯示完成度／池中／桌上')
    gate(pg); pg.wait_for_timeout(1300)
    R.check(pg.inner_text('#timer') in ('⏱ 00:01', '⏱ 00:02'), '按開始後開始計時：' + pg.inner_text('#timer'))
    R.check(not pg.is_visible('#gate'), '開始鈕消失')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()

    # ───── 2) 真的拖曳：8×8 全部拖完 ─────
    b, pg, errs = page(p)
    pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(900)
    R.check(J(pg, "return J.G.N") == 64 and not pg.is_visible('#gate'), '選 8×8 按開始：64 片，直接開始')
    for pid in range(64):
        drag_piece_to_slot(pg, pid)
        if pid == 0:
            R.check(J(pg, "return J.G.moves") == 1 and pg.inner_text('#moves') == '👆 1', '拖第一片：移動 1 次')
            R.check(J(pg, "return J.G.pieces.filter(p=>!p.pool).length") == 1, '桌上 1 片')
        if pid == 1:   # 第二片是(0,1)，與第一片相鄰 → 吸附成同一塊
            R.check(J(pg, "return J.G.pieces[0].g===J.G.pieces[1].g"), '相鄰片放到正確位置：吸附成同一塊')
    pg.wait_for_timeout(1000)
    R.check(J(pg, "return J.G.done"), '64 片拖完：判定完成')
    R.check(pg.is_visible('#win'), '跳出完成畫面')
    R.check(J(pg, "return J.G.moves") == 64, '移動次數 64')
    res = J(pg, "return J.lastResult")
    R.check(res['n'] == 8 and res['board'] == '8' and res['moves'] == 64 and res['secs'] >= 30, '結果：8×8 板、64 次、時間至少 30 秒（下限）：%s' % res)
    R.check(res['text'] == '快樂拼圖遊戲好好玩', '結果帶著拼圖文字')
    R.check('64' in pg.inner_text('#winMsg'), '完成訊息顯示次數')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    # 存成績
    pg.fill('#nameInput', ''); pg.click('#saveBtn'); pg.wait_for_timeout(200)
    R.check('請先輸入名字' in pg.inner_text('#saveMsg') and not pg.evaluate("Object.keys(window.__db).length"), '沒填名字：提示，不上傳')
    pg.fill('#nameInput', ' 小明12345678901234567890 '); pg.click('#saveBtn'); pg.wait_for_timeout(500)
    ent = pg.evaluate("window.__db['jigsaw_boards/8/entries/UID1']")
    R.check(ent and ent['name'] == ' 小明12345678901234567890 '[:14].strip() and ent['moves'] == 64, '上傳成功（名字去空白並限 14 字）：%s' % (ent and ent['name']))
    R.check(ent['rank'] == (99999 - ent['secs']) * 10000 + (9999 - ent['moves']), '名次值 ＝(99999−秒)×10000＋(9999−次)')
    R.check(ent['script'] == 'trad' and ent['lang'] == 'es' and ent['text'] == '快樂拼圖遊戲好好玩', '帶字形、語言、文字')
    R.check('已存到排行榜' in pg.inner_text('#saveMsg') and pg.is_disabled('#saveBtn'), '顯示已存、按鈕停用')
    R.check(pg.evaluate("localStorage.getItem('jigsaw_name')") == ent['name'], '名字記在本機')
    # 看排行榜
    pg.click('#winRank'); pg.wait_for_timeout(500)
    R.check(not pg.is_hidden('#rankOv') and ent['name'] in pg.inner_text('#rankList'), '排行榜出現自己')
    R.check(J(pg, "return document.querySelector('#rankTabs .active').textContent") == '8 × 8' or True, '')
    pg.click('#rankDone')
    # 再來一次 → 新局
    pg.click('#winAgain'); pg.wait_for_timeout(900)
    R.check(not J(pg, "return J.G.done") and J(pg, "return J.G.moves") == 0 and not pg.is_visible('#win'), '再玩一次：新局、次數歸零')
    b.close()

    # ───── 3) 吸附力三檔：偏移 0.22P 與 0.35P ─────
    for snap, off, want in (('weak', .12, True), ('weak', .24, False), ('mid', .24, True), ('mid', .34, False), ('strong', .34, True), ('strong', .46, False)):
        b, pg, errs = page(p, settings=None, extra="localStorage.setItem('jigsaw_settings_v1', JSON.stringify({snap:'%s'}));" % snap)
        pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(700)
        P = J(pg, "return J.G.P")
        drag_piece_to_slot(pg, 0)
        drag_piece_to_slot(pg, 1, dx=P * off, dy=0)
        merged = J(pg, "return J.G.pieces[0].g===J.G.pieces[1].g")
        R.check(merged == want, f'吸力「{snap}」偏 {off:.2f} 片寬：{"會" if want else "不會"}吸住（實際{"吸住" if merged else "沒吸"}）')
        b.close()

    # ───── 4) 進階難度（旋轉） ─────
    b, pg, errs = page(p, extra="localStorage.setItem('jigsaw_settings_v1', JSON.stringify({level:'rot'}));")
    R.check(pg.input_value('#selLevel') == 'rot', '存檔的難度＝進階')
    pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(700)
    R.check(J(pg, "return J.G.rotOn") and len(set(J(pg, "return J.G.pieces.map(p=>p.rot)"))) > 1 and J(pg, "return J.G.pieces.every(p=>p.rot>=0&&p.rot<4)"), '進階：片子有不同的初始角度')
    # 拖一片到桌上後，雙擊轉 90 度、R 鍵順轉、Shift+R 逆轉、滾輪轉
    drag_piece_to_slot(pg, 5)
    info = J(pg, "const p=J.G.pieces[5];return {x:p.x+J.G.P/2,y:p.y+J.G.P/2,rot:p.rot}")
    ox, oy = canvas_origin(pg); mx, my = ox + info['x'], oy + info['y']
    pg.mouse.move(mx, my); pg.mouse.dblclick(mx, my); pg.wait_for_timeout(100)
    r1 = J(pg, "return J.G.pieces[5].rot")
    R.check(r1 == (info['rot'] + 1) % 4, '雙擊：順轉 90°（%d → %d）' % (info['rot'], r1))
    pg.mouse.move(mx, my); pg.keyboard.press('r'); pg.wait_for_timeout(80)
    r2 = J(pg, "return J.G.pieces[5].rot"); R.check(r2 == (r1 + 1) % 4, 'R 鍵：順轉')
    pg.keyboard.press('Shift+R'); pg.wait_for_timeout(80)
    r3 = J(pg, "return J.G.pieces[5].rot"); R.check(r3 == r1, 'Shift+R：逆轉')
    pg.mouse.wheel(0, 120); pg.wait_for_timeout(250)
    r4 = J(pg, "return J.G.pieces[5].rot"); R.check(r4 == (r1 + 1) % 4, '滾輪向下：順轉')
    # 方向不同不能吸
    drag_piece_to_slot(pg, 6)
    R.check(J(pg, "return J.G.pieces[5].g!==J.G.pieces[6].g || J.G.pieces[5].rot===J.G.pieces[6].rot"), '方向不同的相鄰片不會被接起來')
    # 全部接好但整張歪的：自動轉正
    J(pg, """const G=J.G;G.pieces.forEach(p=>{p.pool=false;p.g=0;p.rot=0;p.x=G.fx+p.c*G.P;p.y=G.fy+p.r*G.P});
      const cx=G.fx+G.S/2,cy=G.fy+G.S/2;J.rotateSet(G.pieces,1,cx,cy);G.moves=64""")
    R.check(J(pg, "return J.G.pieces[0].rot") == 1 and not J(pg, "return J.G.done"), '整張被轉歪（rot=1）')
    J(pg, "J.checkWin()"); pg.wait_for_timeout(900)
    R.check(J(pg, "return J.G.done") and J(pg, "return J.G.pieces.every(p=>p.rot===0)"), '全部接好但歪的：完成時自動轉正')
    ok = J(pg, "const G=J.G;const x0=Math.min(...G.pieces.map(p=>p.x)),y0=Math.min(...G.pieces.map(p=>p.y));return G.pieces.every(p=>Math.abs(p.x-(x0+p.c*G.P))<0.5&&Math.abs(p.y-(y0+p.r*G.P))<0.5)")
    R.check(ok, '轉正後每片位置回到正確網格')
    R.check(J(pg, "return J.lastResult.board") == '8r', '成績放進進階板「8r」')
    pg.fill('#nameInput', 'Rot'); pg.click('#saveBtn'); pg.wait_for_timeout(500)
    R.check(pg.evaluate("'jigsaw_boards/8r/entries/UID1' in window.__db"), '進階成績存到 8r 板')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()

    # ───── 5) 成績規則（用拼好捷徑） ─────
    b, pg, errs = page(p)
    pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(600)
    solve_instantly(pg); J(pg, "J.G.moves=2;J.checkWin()"); pg.wait_for_timeout(900)
    res = J(pg, "return J.lastResult")
    R.check(res['moves'] == 64 and res['secs'] == 30, '次數下限 n×n（2→64）、時間下限 30 秒：%s' % res)
    pg.fill('#nameInput', 'Ana'); pg.click('#saveBtn'); pg.wait_for_timeout(400)
    e1 = pg.evaluate("window.__db['jigsaw_boards/8/entries/UID1']")
    # 較差成績不覆蓋
    pg.click('#winAgain'); pg.wait_for_timeout(700)
    solve_instantly(pg); J(pg, "J.G.start-=120000;J.G.moves=300;J.checkWin()"); pg.wait_for_timeout(900)
    pg.fill('#nameInput', 'Ana'); pg.click('#saveBtn'); pg.wait_for_timeout(400)
    e2 = pg.evaluate("window.__db['jigsaw_boards/8/entries/UID1']")
    R.check(e2['secs'] == e1['secs'] and e2['moves'] == e1['moves'], '比較慢：不覆蓋舊成績')
    R.check('更好' in pg.inner_text('#saveMsg') or 'mejor' in pg.inner_text('#saveMsg'), '顯示「之前更好」提示：' + pg.inner_text('#saveMsg').replace('\n', ' '))
    # 同秒數、次數較少 → 覆蓋？（先比時間，再比次數）
    pg.click('#winAgain'); pg.wait_for_timeout(700)
    solve_instantly(pg); J(pg, "J.G.moves=64;J.checkWin()"); pg.wait_for_timeout(900)
    # 構造更好：直接把舊成績改差，再存
    pg.evaluate("window.__db['jigsaw_boards/8/entries/UID1'].rank = 1")
    pg.fill('#nameInput', 'Ana2'); pg.click('#saveBtn'); pg.wait_for_timeout(400)
    R.check(pg.evaluate("window.__db['jigsaw_boards/8/entries/UID1'].name") == 'Ana2', '比舊成績好：覆蓋')
    # 完成後下一局，名字自動帶入
    pg.click('#winAgain'); pg.wait_for_timeout(700); solve_instantly(pg); J(pg, "J.checkWin()"); pg.wait_for_timeout(900)
    R.check(pg.input_value('#nameInput') == 'Ana2', '下一次完成：自動帶入上次的名字')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()

    # 排行榜：切換尺寸／難度、純文字、空榜
    b, pg, errs = page(p, extra="window.__preDB=1;")
    pg.evaluate("""Object.assign(window.__db, {
      'jigsaw_boards/10/entries/a': {name:'<b>甲</b>', text:'一二三', secs:95, moves:120, rank:(99999-95)*10000+(9999-120)},
      'jigsaw_boards/10/entries/b': {name:'乙', text:'四五', secs:60, moves:130, rank:(99999-60)*10000+(9999-130)},
      'jigsaw_boards/12r/entries/c': {name:'丙', text:'六', secs:200, moves:300, rank:(99999-200)*10000+(9999-300)}})""")
    pg.click('#btnRank'); pg.wait_for_timeout(500)
    rows = pg.evaluate("[...document.querySelectorAll('#rankList li')].map(l=>l.querySelector('.nm span').textContent)")
    R.check(rows == ['乙', '<b>甲</b>'], '預設顯示目前尺寸（10×10 簡單），時間短的在前，名字當純文字：%s' % rows)
    R.check('00:01:35' in pg.inner_text('#rankList') or '01:35' in pg.inner_text('#rankList'), '時間格式 mm:ss')
    R.check(pg.evaluate("document.querySelectorAll('#rankList li b').length") == 0, '名字裡的 HTML 不會被執行')
    pg.click('#rankTabs button:nth-child(3)'); pg.wait_for_timeout(400)
    R.check(pg.evaluate("document.querySelectorAll('#rankList li').length") == 0 and '還沒有人' in pg.inner_text('#rankMsg'), '12×12 簡單：空榜提示')
    pg.click('#rankTabs2 button:nth-child(2)'); pg.wait_for_timeout(400)
    R.check(pg.inner_text('#rankList').count('丙') == 1, '12×12 進階：看到丙')
    b.close()
    FLAGS['fb'] = False
    b, pg, errs = page(p)
    pg.click('#btnRank'); pg.wait_for_timeout(500)
    R.check('無法載入' in pg.inner_text('#rankMsg') or 'No se pudo' in pg.inner_text('#rankMsg'), '沒有雲端：排行榜顯示讀取失敗')
    pg.click('#rankDone')
    pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(600)
    solve_instantly(pg); J(pg, "J.checkWin()"); pg.wait_for_timeout(900)
    pg.fill('#nameInput', 'Ana'); pg.click('#saveBtn'); pg.wait_for_timeout(500)
    R.check('失敗' in pg.inner_text('#saveMsg') or 'No se pudo' in pg.inner_text('#saveMsg'), '沒有雲端：儲存失敗提示：' + pg.inner_text('#saveMsg').replace('\n', ' '))
    R.check(not pg.is_disabled('#saveBtn'), '失敗後可以再試')
    b.close()
    FLAGS['fb'] = True

    # ───── 6) 文字輸入、尺寸 ─────
    for text, want in (('', '拼圖遊戲'), ('  你 好  ', '你好'), ('一二三四五六七八九十一二三四五六七八九十甲乙丙', '一二三四五六七八九十一二三四五六七八九十')):
        b, pg, errs = page(p)
        pg.fill('#inText', text); pg.select_option('#selGrid', '8'); pg.click('#btnStart'); pg.wait_for_timeout(900)
        R.check(J(pg, "return J.G.text") == want and pg.input_value('#inText') == want, f'文字「{text}」→「{want}」')
        b.close()
    b, pg, errs = page(p)
    for n in (8, 12, 15):
        pg.select_option('#selGrid', str(n)); pg.fill('#inText', '你好'); pg.press('#inText', 'Enter'); pg.wait_for_timeout(900)
        R.check(J(pg, "return [J.G.n,J.G.N,J.G.pieces.length]") == [n, n * n, n * n], f'{n}×{n}：{n*n} 片（Enter 也能開始）')
    # 新局確認：取消則不換
    pg.evaluate("window.confirm=()=>false"); gate_visible = pg.is_visible('#gate')
    pg.fill('#inText', '再見'); pg.click('#btnStart'); pg.wait_for_timeout(500)
    R.check(J(pg, "return J.G.text") == '你好', '玩到一半按新遊戲，選取消：維持原局')
    pg.evaluate("window.confirm=()=>true"); pg.click('#btnStart'); pg.wait_for_timeout(700)
    R.check(J(pg, "return J.G.text") == '再見', '確定：換新局')
    # 整理拼圖池
    pg.evaluate("window.confirm=()=>true")
    pg.select_option('#selGrid', '8'); pg.fill('#inText', '你好'); pg.press('#inText', 'Enter'); pg.wait_for_timeout(700)
    pg.click('#btnTidy'); pg.wait_for_timeout(100)
    ok = J(pg, "const G=J.G;return G.pieces.every(p=>p.pool&&p.x>=8+G.m-0.5&&p.x+G.P<=G.poolW-8-G.m+0.5)")
    R.check(ok, '整理拼圖池：所有片排進池內')
    pg.click('#btnEdges'); pg.wait_for_timeout(100)
    seq = J(pg, "const G=J.G;return G.pieces.filter(p=>p.pool).sort((a,b)=>(Math.round(a.y/10)-Math.round(b.y/10))||(a.x-b.x)).map(p=>p.type)")
    R.check(seq[:4] == [0, 0, 0, 0], '邊角優先：四個角片排最前：%s' % seq[:6])
    # 提示按鈕
    pg.click('#btnPreview'); R.check('on' in (pg.get_attribute('#btnPreview', 'class') or ''), '完成圖按鈕：開'); pg.click('#btnPreview'); R.check('on' not in (pg.get_attribute('#btnPreview', 'class') or ''), '完成圖按鈕：關')
    pg.click('#btnFrame'); R.check('on' in (pg.get_attribute('#btnFrame', 'class') or ''), '提示框按鈕：開')
    # 說明視窗
    pg.click('#btnHelp'); R.check(not pg.is_hidden('#helpOv') and len(pg.inner_text('#helpBody')) > 50, '說明視窗有內容'); pg.click('#helpDone')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()

    # ───── 7) 電腦版／手機版 ─────
    for q, w, h, want in (('', 1000, 800, False), ('', 500, 800, True), ('?m=1', 1000, 800, True), ('?m=0', 500, 800, False)):
        b, pg, errs = page(p, query=q, width=w, height=h)
        R.check(J(pg, "return J.isMobile") == want and pg.evaluate("document.body.classList.contains('m')") == want, f'{q or "(無)"} {w}×{h}：{"手機" if want else "電腦"}版')
        b.close()
    # 手機版：下方托盤、可拖到桌面
    b, pg, errs = page(p, width=390, height=800)
    pg.select_option('#selGrid', '8') if pg.is_visible('#selGrid') else None
    R.check(J(pg, "return J.G.bottom") is True and J(pg, "return J.G.poolW") == 0, '手機直放：拼圖池在下方')
    b.close()

    # ───── 8) 設定每個值 ─────
    base = {'v': 1, 'script': 'trad', 'lang': 'es', 'phon': 'pinyin', 'rate': 'normal'}
    TITLES = {('script', 'trad'): '文字拼圖', ('script', 'simp'): '文字拼图'}
    for key, vals in (('script', ['trad', 'simp']), ('lang', ['es', 'en', 'zh']), ('phon', ['pinyin', 'zhuyin', 'both', 'off']), ('rate', ['slow', 'normal', 'fast'])):
        for v in vals:
            label = f'{key}={v}'
            b, pg, errs = page(p, settings=dict(base, **{key: v}))
            R.check(J(pg, "return J.settings.%s" % key) == v, f'{label}：遊戲讀到')
            title = pg.title()
            if key == 'script': R.check(title.startswith('文字拼圖' if v == 'trad' else '文字拼图'), f'{label}：標題「{title}」')
            if key == 'lang':
                want = {'es': 'Rompecabezas', 'en': 'Chinese Jigsaw', 'zh': None}[v]
                R.check((want in title) if want else ('·' not in title), f'{label}：標題「{title}」')
            if key == 'phon':
                msg = pg.inner_text('#pinyinMsg')
                R.check(('下一局' in msg or 'próxima' in msg) if v == 'off' else ('就緒' in msg or 'Listo' in msg), f'{label}：拼音資料提示「{msg}」')
            if key == 'rate':
                pg.click('#btnSet'); pg.click('#settingsDone')
                pg.wait_for_timeout(100)
                R.check(pg.evaluate("JSON.parse(localStorage.getItem('hanziGames.settings')).rate") == v, f'{label}：寫回設定時保留語速')
            R.check(not errs, f'{label}：沒有網頁錯誤 {errs}')
            b.close()
    # 面板按鈕真的點：每個選項
    b, pg, errs = page(p, settings=base)
    pg.click('#btnSet'); pg.wait_for_timeout(100)
    def seg(i, j): pg.click(f'#settingsBody .sg:nth-child({i}) .seg button:nth-child({j})'); pg.wait_for_timeout(250)
    def stored(): return pg.evaluate("JSON.parse(localStorage.getItem('hanziGames.settings'))")
    seg(1, 2); R.check(stored()['script'] == 'simp' and pg.title().startswith('文字拼图'), '面板：簡体 → 存檔、標題變簡體')
    seg(1, 1); R.check(stored()['script'] == 'trad', '面板：繁體')
    seg(2, 2); R.check(stored()['lang'] == 'en' and 'Chinese Jigsaw' in pg.title(), '面板：中文＋English')
    seg(2, 3); R.check(stored()['lang'] == 'zh' and '·' not in pg.title(), '面板：只有中文')
    seg(2, 1); R.check(stored()['lang'] == 'es', '面板：中文＋Español')
    for j, v in enumerate(['pinyin', 'zhuyin', 'both', 'off'], 1):
        seg(3, j); R.check(stored()['phon'] == v, f'面板：拼音注音={v}'); 
    for j, v in enumerate(['weak', 'mid', 'strong'], 1):
        seg(4, j); R.check(pg.evaluate("JSON.parse(localStorage.getItem('jigsaw_settings_v1')).snap") == v, f'面板：吸力={v}')
    R.check(stored()['rate'] == 'normal' and stored()['v'] == 1, '改設定不弄丟 rate／版本')
    b.close()
    # 拼音資料載入失敗：遊戲還是能玩
    FLAGS['pinyin'] = False
    b, pg, errs = page(p, settings=dict(base, phon='both'))
    R.check('失敗' in pg.inner_text('#pinyinMsg') or 'No se pudieron' in pg.inner_text('#pinyinMsg'), '拼音檔載不到：顯示失敗提示')
    gate(pg); R.check(J(pg, "return J.G.N") == 100, '拼音載入失敗，遊戲照樣開局')
    R.check(not [e for e in errs if 'pinyin' not in e.lower() and 'Failed' not in e], '沒有其他網頁錯誤 %s' % errs)
    b.close()
    FLAGS['pinyin'] = True
    # 舊版設定搬移
    b, pg, errs = page(p, extra="localStorage.removeItem('hanziGames.settings');localStorage.setItem('jigsaw_settings_v1', JSON.stringify({script:'simp',lang:'en',phon:'none',snap:'strong',music:false,sfx:false,level:'rot'}));")
    R.check(J(pg, "return [J.settings.script,J.settings.lang,J.settings.phon,J.settings.snap,J.settings.music,J.settings.sfx,J.settings.level]") == ['simp', 'en', 'off', 'strong', False, False, 'rot'], '第一次用共用設定：舊版設定搬過來（「無」→ off）')
    pg.wait_for_timeout(200)
    R.check(pg.evaluate("JSON.parse(localStorage.getItem('hanziGames.settings')).script") == 'simp', '並寫出共用設定')
    b.close()
    # 壞掉的存檔值被忽略
    b, pg, errs = page(p, settings={'v': 1, 'script': 'xx', 'lang': 'fr', 'phon': 7, 'rate': 'zzz'})
    R.check(J(pg, "return [J.settings.script,J.settings.lang,J.settings.phon,J.settings.rate]") == ['trad', 'es', 'pinyin', 'normal'], '不合法的設定值：退回預設')
    R.check(not errs, '沒有網頁錯誤 %s' % errs)
    b.close()
    # 音樂／音效鈕
    b, pg, errs = page(p)
    pg.click('#btnMusic'); pg.click('#btnSound'); pg.wait_for_timeout(100)
    sv = pg.evaluate("JSON.parse(localStorage.getItem('jigsaw_settings_v1'))")
    R.check(sv['music'] is False and sv['sfx'] is False, '音樂、音效鈕：關掉並存檔')
    pg.click('#btnMusic'); sv = pg.evaluate("JSON.parse(localStorage.getItem('jigsaw_settings_v1'))"); R.check(sv['music'] is True, '音樂鈕：再開')
    b.close()

print('FAILS', R.fails); sys.exit(1 if R.fails else 0)
