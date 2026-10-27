// Processo principal: janela estilo Discord, ícone na bandeja, início com o Windows,
// atalhos globais e o motor de voz (Python) rodando escondido em segundo plano.

const { app, BrowserWindow, Tray, Menu, ipcMain, globalShortcut, Notification, nativeImage, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const readline = require('readline');

const VOZ = path.join(__dirname, '..', 'voz');
const PYTHON = path.join(VOZ, '.venv', 'Scripts', 'python.exe');
const ICONES = path.join(__dirname, 'icones');

let janela = null;
let bandeja = null;
let motor = null;
let saindo = false;
let estadoAtual = 'carregando';
let mudo = false;

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', mostrar);

// Inicia junto com o Windows, já minimizado na bandeja.
app.setLoginItemSettings({ openAtLogin: true, path: process.execPath, args: [app.getAppPath(), '--oculto'] });

function mostrar() {
  if (!janela) return;
  if (janela.isMinimized()) janela.restore();
  janela.show();
  janela.focus();
}

function criarJanela() {
  janela = new BrowserWindow({
    width: 1180, height: 760, minWidth: 820, minHeight: 520,
    backgroundColor: '#313338',
    title: 'Secretário',
    icon: path.join(ICONES, 'app.png'),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#1e1f22', symbolColor: '#b5bac1', height: 30 },
    show: !process.argv.includes('--oculto'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  janela.loadFile('index.html');
  // Fechar só esconde (igual ao Discord); sair de verdade é pela bandeja.
  janela.on('close', (e) => { if (!saindo) { e.preventDefault(); janela.hide(); } });
  janela.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

function atualizarBandeja() {
  if (!bandeja) return;
  const icone = mudo ? 'mudo' : ({ pensando: 'ocupado', falando: 'ocupado', escutando: 'ouvindo' }[estadoAtual] || 'app');
  bandeja.setImage(nativeImage.createFromPath(path.join(ICONES, `${icone}.png`)).resize({ width: 16, height: 16 }));
  const rotulo = { carregando: 'carregando…', ouvindo: 'ouvindo', escutando: 'escutando você', pensando: 'trabalhando',
    falando: 'falando', mudo: 'microfone mudo', parado: 'motor parado' }[estadoAtual] || estadoAtual;
  bandeja.setToolTip(`Secretário — ${rotulo}`);
  bandeja.setContextMenu(Menu.buildFromTemplate([
    { label: 'Abrir Secretário', click: mostrar },
    { label: 'Microfone mudo', type: 'checkbox', checked: mudo, click: (i) => alternarMudo(i.checked) },
    { label: 'Abrir memória (Obsidian)', click: () => shell.openExternal('obsidian://open?vault=Secretario') },
    { type: 'separator' },
    { label: 'Reiniciar motor de voz', click: () => { if (motor) motor.kill(); } },
    { label: 'Sair', click: () => { saindo = true; app.quit(); } },
  ]));
}

function enviarAoMotor(cmd) {
  if (motor && motor.stdin.writable) motor.stdin.write(JSON.stringify(cmd) + '\n');
}

function alternarMudo(valor) {
  mudo = valor;
  enviarAoMotor({ cmd: 'mudo', valor });
  if (janela) janela.webContents.send('evento', { evento: 'mudo', valor });
  atualizarBandeja();
}

function iniciarMotor() {
  motor = spawn(PYTHON, ['assistente_voz.py', '--ipc'], {
    cwd: VOZ, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
  });
  readline.createInterface({ input: motor.stdout }).on('line', (linha) => {
    let ev;
    try { ev = JSON.parse(linha); } catch { return; }
    if (ev.evento === 'estado') { estadoAtual = ev.estado; atualizarBandeja(); }
    if (ev.evento === 'mensagem' && ev.autor === 'secretario' && janela && !janela.isVisible()) {
      const n = new Notification({ title: 'Secretário', body: ev.texto.slice(0, 200), icon: path.join(ICONES, 'app.png') });
      n.on('click', mostrar);
      n.show();
    }
    if (janela) janela.webContents.send('evento', ev);
  });
  let erros = '';
  motor.stderr.on('data', (d) => { erros = (erros + d.toString()).slice(-2000); });
  motor.on('exit', (codigo) => {
    motor = null;
    estadoAtual = 'parado';
    atualizarBandeja();
    if (saindo) return;
    if (janela) janela.webContents.send('evento', { evento: 'erro', texto: `Motor de voz parou (código ${codigo}). Reiniciando…\n${erros.slice(-400)}` });
    setTimeout(() => { iniciarMotor(); if (mudo) enviarAoMotor({ cmd: 'mudo', valor: true }); }, 3000);
  });
}

ipcMain.on('cmd', (_e, cmd) => {
  if (cmd.cmd === 'mudo') return alternarMudo(cmd.valor);
  if (cmd.cmd === 'obsidian') return shell.openExternal('obsidian://open?vault=Secretario');
  enviarAoMotor(cmd);
});
ipcMain.handle('estado', () => ({ estado: estadoAtual, mudo }));

app.whenReady().then(() => {
  app.setAppUserModelId('Secretario.Deivid');
  criarJanela();
  bandeja = new Tray(nativeImage.createFromPath(path.join(ICONES, 'app.png')).resize({ width: 16, height: 16 }));
  bandeja.on('click', mostrar);
  atualizarBandeja();
  iniciarMotor();

  // Ctrl+Shift+Espaço: falar sem dizer "secretário". Ctrl+Shift+S: abre/esconde a janela.
  globalShortcut.register('Control+Shift+Space', () => {
    enviarAoMotor({ cmd: 'ouvir_agora' });
    if (janela) janela.webContents.send('evento', { evento: 'estado', estado: 'escutando' });
  });
  globalShortcut.register('Control+Shift+S', () => (janela.isVisible() && janela.isFocused() ? janela.hide() : mostrar()));
});

app.on('before-quit', () => { saindo = true; enviarAoMotor({ cmd: 'sair' }); setTimeout(() => motor && motor.kill(), 1500); });
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', (e) => e.preventDefault());
