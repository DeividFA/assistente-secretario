const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('secretario', {
  enviar: (cmd) => ipcRenderer.send('cmd', cmd),
  estado: () => ipcRenderer.invoke('estado'),
  aoEvento: (cb) => ipcRenderer.on('evento', (_e, ev) => cb(ev)),
});
