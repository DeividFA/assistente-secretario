// Processo principal: janela estilo Discord, ícone na bandeja, início com o Windows,
// atalhos globais e o motor de voz (Python) rodando escondido em segundo plano.

const { app, BrowserWindow, Tray, Menu, ipcMain, globalShortcut, Notification, nativeImage, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const VOZ = path.join(__dirname, '..', 'voz');
const PYTHON = path.join(VOZ, '.venv', 'Scripts', 'python.exe');
const ICONES = path.join(__dirname, 'icones');
const LEMBRETES = path.join(VOZ, 'lembretes.json');
const COFRE = path.join(require('os').homedir(), 'Documents', 'Secretario'); // não usar getPath('documents'): aponta para o OneDrive
const CONFIG_OBSIDIAN = path.join(app.getPath('appData'), 'obsidian', 'obsidian.json');

let janela = null;
let bandeja = null;
let motor = null;
let reiniciando = false; // reinício pedido de propósito (não é erro)

// O python.exe do venv é só um lançador que abre o Python real como filho:
// matar só ele deixaria o motor órfão segurando o microfone. Mata a árvore toda.
function matarMotor() {
  if (motor) spawn('taskkill', ['/pid', String(motor.pid), '/T', '/F'], { windowsHide: true });
}
function reiniciarMotor() {
  if (!motor) return;
  reiniciando = true;
  matarMotor();
}
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
    backgroundColor: '#0f1012',
    title: 'Secretário',
    icon: path.join(ICONES, 'app.png'),
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#0f1012', symbolColor: '#a9adb6', height: 32 },
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
    { label: 'Abrir memória (Obsidian)', click: abrirObsidian },
    { type: 'separator' },
    { label: 'Reiniciar motor de voz', click: reiniciarMotor },
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

// O Obsidian só abre cofres que conhece; se ele "esqueceu" o do secretário, registra de novo.
function abrirObsidian() {
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_OBSIDIAN, 'utf8'));
    config.vaults = config.vaults || {};
    const conhecido = Object.values(config.vaults).some((v) => path.resolve(v.path).toLowerCase() === COFRE.toLowerCase());
    if (!conhecido) {
      config.vaults['5ec7e7a7a1b2c3d4'] = { path: COFRE, ts: Date.now(), open: false };
      fs.writeFileSync(CONFIG_OBSIDIAN, JSON.stringify(config));
    }
  } catch (erro) {
    if (erro.code === 'ENOENT') {
      fs.mkdirSync(path.dirname(CONFIG_OBSIDIAN), { recursive: true });
      fs.writeFileSync(CONFIG_OBSIDIAN, JSON.stringify({ vaults: { '5ec7e7a7a1b2c3d4': { path: COFRE, ts: Date.now(), open: true } } }));
    }
  }
  shell.openExternal('obsidian://open?vault=Secretario&file=' + encodeURIComponent('00 - Índice'));
}

function verificarLembretes() {
  try {
    const lembretes = JSON.parse(fs.readFileSync(LEMBRETES, 'utf8'));
    const agora = Date.now();
    let alterado = false;
    for (const lembrete of lembretes) {
      if (lembrete.feito !== false || !(new Date(lembrete.quando).getTime() <= agora)) continue;
      const n = new Notification({ title: 'Secretário — Lembrete', body: lembrete.texto, icon: path.join(ICONES, 'app.png') });
      n.on('click', mostrar);
      n.show();
      lembrete.feito = true;
      alterado = true;
    }
    if (alterado) fs.writeFileSync(LEMBRETES, JSON.stringify(lembretes, null, 2), 'utf8');
  } catch (erro) {
    if (erro.code !== 'ENOENT') console.error('Não foi possível verificar os lembretes:', erro);
  }
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
    if (janela) {
      const ev = reiniciando
        ? { evento: 'mensagem', autor: 'sistema', texto: 'Reiniciando o motor de voz…' }
        : { evento: 'erro', texto: `Motor de voz parou (código ${codigo}). Reiniciando…\n${erros.slice(-400)}` };
      janela.webContents.send('evento', ev);
    }
    reiniciando = false;
    setTimeout(() => { iniciarMotor(); if (mudo) enviarAoMotor({ cmd: 'mudo', valor: true }); }, 3000);
  });
}

ipcMain.on('cmd', (_e, cmd) => {
  if (cmd.cmd === 'mudo') return alternarMudo(cmd.valor);
  if (cmd.cmd === 'obsidian') return abrirObsidian();
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
  setInterval(verificarLembretes, 30000);

  // Ctrl+Shift+Espaço: falar sem dizer "secretário". Ctrl+Shift+S: abre/esconde a janela.
  globalShortcut.register('Control+Shift+Space', () => {
    enviarAoMotor({ cmd: 'ouvir_agora' });
    if (janela) janela.webContents.send('evento', { evento: 'estado', estado: 'escutando' });
  });
  globalShortcut.register('Control+Shift+S', () => (janela.isVisible() && janela.isFocused() ? janela.hide() : mostrar()));
});

app.on('before-quit', () => { saindo = true; enviarAoMotor({ cmd: 'sair' }); setTimeout(matarMotor, 1500); });
app.on('will-quit', () => globalShortcut.unregisterAll());
app.on('window-all-closed', (e) => e.preventDefault());
