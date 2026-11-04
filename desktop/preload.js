// The only bridge between the Bit web app and the desktop. Kept tiny on purpose (contextIsolation + sandbox).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bitDesktop', {
  platform: process.platform,
  expand: () => ipcRenderer.invoke('bit:expand'),
  collapse: () => ipcRenderer.invoke('bit:collapse'),
  setMode: (m) => ipcRenderer.invoke('bit:mode', String(m)),
  setIgnore: (on) => ipcRenderer.invoke('bit:ignore', !!on),
  capture: (aroundCursor) => ipcRenderer.invoke('bit:capture', !!aroundCursor),
  clipboard: () => ipcRenderer.invoke('bit:clipboard'),
  setServer: (url) => ipcRenderer.invoke('bit:set-server', String(url || '')),
  onExplain: (cb) => ipcRenderer.on('bit:explain', (_e, data) => cb(data)),
  onCollapsed: (cb) => ipcRenderer.on('bit:collapsed', () => cb()),
});
