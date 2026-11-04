// Bit desktop: a small always-on-top robot in the screen corner. Click it to ask; Ctrl+Shift+Space explains
// whatever is under the mouse cursor (a word in a book, an error in a terminal, a chart...).
// The UI is the Bit web app served by your Bit server; this file only adds desktop powers.
const { app, BrowserWindow, ipcMain, screen, desktopCapturer, globalShortcut, clipboard, Tray, Menu, shell, nativeImage, session, systemPreferences } = require('electron');
const path = require('path');
const fs = require('fs');

if (process.platform === 'linux') app.commandLine.appendSwitch('enable-transparent-visuals');
if (!app.requestSingleInstanceLock()) app.quit();

const CFG_FILE = path.join(app.getPath('userData'), 'config.json');
// window sizes: the robot always sits in the bottom-right corner of the window, so it does not jump
const SIZES = { widget: { width: 190, height: 236 }, ask: { width: 420, height: 500 }, board: { width: 940, height: 720 } };
const WIDGET = SIZES.widget;
const HOTKEY = 'CommandOrControl+Shift+Space';

let cfg = {};
let win = null;
let tray = null;
let mode = 'widget';

function loadCfg() { try { cfg = JSON.parse(fs.readFileSync(CFG_FILE, 'utf8')); } catch { cfg = {}; } }
function saveCfg() { fs.mkdirSync(path.dirname(CFG_FILE), { recursive: true }); fs.writeFileSync(CFG_FILE, JSON.stringify(cfg, null, 2)); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function serverOrigin() { try { return new URL(cfg.server).origin; } catch { return null; } }
function isOurs(url) { return url.startsWith('file:') || (serverOrigin() && url.startsWith(serverOrigin())); }

function clampToScreen(b) {
  const wa = screen.getDisplayMatching(b).workArea;
  return { ...b, x: Math.min(Math.max(b.x, wa.x), wa.x + wa.width - b.width), y: Math.min(Math.max(b.y, wa.y), wa.y + wa.height - b.height) };
}

function widgetBounds() {
  if (cfg.widget) return clampToScreen({ ...cfg.widget, ...WIDGET });
  const wa = screen.getPrimaryDisplay().workArea;
  return { x: wa.x + wa.width - WIDGET.width - 18, y: wa.y + wa.height - WIDGET.height - 18, ...WIDGET };
}

function setMode(next) {
  if (!win) return;
  if (next === 'panel') next = 'board';
  if (!SIZES[next]) return;
  const cur = win.getBounds(), size = SIZES[next];
  const wa = screen.getDisplayMatching(cur).workArea;
  const w = Math.min(size.width, wa.width), h = Math.min(size.height, wa.height);
  // keep the bottom-right corner (where the robot is) fixed
  win.setBounds(clampToScreen({ x: cur.x + cur.width - w, y: cur.y + cur.height - h, width: w, height: h }), false);
  win.setSkipTaskbar(next === 'widget');
  if (next !== 'widget') win.focus();
  if (next === 'widget') win.webContents.send('bit:collapsed');
  mode = next;
}

function createWindow() {
  win = new BrowserWindow({
    ...widgetBounds(), frame: false, transparent: true, resizable: false, alwaysOnTop: true, skipTaskbar: true,
    hasShadow: false, show: false, backgroundColor: '#00000000', icon: path.join(__dirname, 'build/icon.png'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  // links to other sites open in the normal browser; the window only ever shows Bit
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!isOurs(url)) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); } });
  win.on('moved', () => {   // remember where the robot (bottom-right corner) is
    const b = win.getBounds(); cfg.widget = { x: b.x + b.width - WIDGET.width, y: b.y + b.height - WIDGET.height }; saveCfg();
  });
  // Windows/macOS: clicks on transparent areas go through to the apps below (the page tells us where it is solid)
  if (process.platform !== 'linux') win.setIgnoreMouseEvents(true, { forward: true });
  win.once('ready-to-show', () => win.show());
  win.webContents.on('did-fail-load', (_e, code, desc, url) => {
    if (isOurs(url) && !url.startsWith('file:')) win.loadFile('setup.html');   // server not reachable -> ask again
  });

  if (cfg.server) win.loadURL(cfg.server.replace(/\/+$/, '') + '/?desktop=1');
  else { win.loadFile('setup.html'); setMode('ask'); }
}

// Screenshot of the screen under the mouse; Bit's own window is hidden for the shot.
async function capture(aroundCursor) {
  const pt = screen.getCursorScreenPoint();
  const disp = screen.getDisplayNearestPoint(pt);
  const sf = disp.scaleFactor || 1;
  win.setOpacity(0); await sleep(140);
  let sources;
  try {
    sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: Math.round(disp.size.width * sf), height: Math.round(disp.size.height * sf) } });
  } finally { win.setOpacity(1); }
  const src = sources.find((s) => s.display_id === String(disp.id)) || sources[0];
  if (!src) throw new Error('no screen source (on macOS allow Screen Recording for Bit)');
  let img = src.thumbnail;
  const size = img.getSize();
  if (aroundCursor) {
    const kx = size.width / disp.bounds.width, ky = size.height / disp.bounds.height;
    const cx = Math.round((pt.x - disp.bounds.x) * kx), cy = Math.round((pt.y - disp.bounds.y) * ky);
    const w = Math.min(size.width, Math.round(900 * kx)), h = Math.min(size.height, Math.round(420 * ky));
    const x = Math.min(Math.max(cx - Math.round(w / 2), 0), size.width - w), y = Math.min(Math.max(cy - Math.round(h / 2), 0), size.height - h);
    img = img.crop({ x, y, width: w, height: h });
  } else if (size.width > 1600) {
    img = img.resize({ width: 1600 });
  }
  return 'data:image/jpeg;base64,' + img.toJPEG(82).toString('base64');
}

async function explainUnderCursor() {
  if (!win || !cfg.server) return;
  const selection = process.platform === 'linux' ? clipboard.readText('selection').trim().slice(0, 500) : '';
  let image = null;
  try { image = await capture(true); } catch (e) { console.error(e); }
  setMode('ask'); win.show(); win.focus();
  win.webContents.send('bit:explain', { image, text: selection });
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'build/icon.png')).resize({ width: 18, height: 18 });
  tray = new Tray(icon);
  tray.setToolTip('Bit');
  const login = app.getLoginItemSettings().openAtLogin;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Bitni koʻrsatish', click: () => { win.show(); setMode('ask'); } },
    { label: 'Burchakka kichraytirish', click: () => setMode('widget') },
    { label: `Kursor ostidagini tushuntir (${HOTKEY.replace('CommandOrControl', 'Ctrl')})`, click: explainUnderCursor },
    { type: 'separator' },
    { label: 'Server manzilini oʻzgartirish', click: () => { setMode('board'); win.loadFile('setup.html'); } },
    { label: 'Kompyuter yonganda ochilsin', type: 'checkbox', checked: login, visible: process.platform !== 'linux',
      click: (item) => app.setLoginItemSettings({ openAtLogin: item.checked }) },
    { type: 'separator' },
    { label: 'Chiqish', click: () => app.quit() },
  ]));
  tray.on('click', () => { if (!win.isVisible()) win.show(); setMode(mode === 'widget' ? 'ask' : 'widget'); });
}

ipcMain.handle('bit:expand', () => setMode('ask'));
ipcMain.handle('bit:collapse', () => setMode('widget'));
ipcMain.handle('bit:mode', (_e, m) => setMode(m));
ipcMain.handle('bit:ignore', (_e, on) => { if (win && process.platform !== 'linux') win.setIgnoreMouseEvents(!!on, { forward: true }); });
ipcMain.handle('bit:capture', (_e, around) => capture(around));
ipcMain.handle('bit:clipboard', () => {
  const sel = process.platform === 'linux' ? clipboard.readText('selection') : '';
  return (sel || clipboard.readText() || '').trim().slice(0, 2000);
});
ipcMain.handle('bit:set-server', async (_e, url) => {
  let u;
  try { u = new URL(url); } catch { return 'Manzil notoʻgʻri. Masalan: http://127.0.0.1:8001'; }
  if (!/^https?:$/.test(u.protocol)) return 'Faqat http:// yoki https://';
  try { const r = await fetch(u.origin + '/api/health'); if (!r.ok) throw new Error(); } catch { return 'Server javob bermadi: ' + u.origin + ' (Bit server ishlayaptimi?)'; }
  cfg.server = u.origin; saveCfg();
  win.loadURL(cfg.server + '/?desktop=1'); setMode('widget');
  return true;
});

app.on('second-instance', () => { if (win) { win.show(); setMode('ask'); } });
app.whenReady().then(() => {
  loadCfg();
  if (process.platform === 'darwin') systemPreferences.askForMediaAccess('microphone').catch(() => {});
  // microphone / camera / notifications only for the Bit server; screen capture goes through capture() above
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => cb(isOurs(wc.getURL()) && ['media', 'notifications', 'clipboard-read'].includes(perm)));
  createWindow();
  buildTray();
  if (!globalShortcut.register(HOTKEY, explainUnderCursor)) console.warn('hotkey busy:', HOTKEY);
});
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', () => app.quit());
