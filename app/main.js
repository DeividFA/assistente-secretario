// Processo principal: janela estilo Discord, ícone na bandeja, início com o Windows,
// atalhos globais e o motor de voz (Python) rodando escondido em segundo plano.

const { app, BrowserWindow, Tray, Menu, ipcMain, globalShortcut, Notification, nativeImage, shell, dialog } = require('electron');
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const VOZ = path.join(__dirname, '..', 'voz');
const PYTHON = path.join(VOZ, '.venv', 'Scripts', 'python.exe');
const ICONES = path.join(__dirname, 'icones');
const LEMBRETES = path.join(VOZ, 'lembretes.json');
const SINAIS = path.join(VOZ, 'sinais');
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
let motores = { lista: [], atual: null };
let ponte = { ativa: false, aparelhos: [] };
let vozes = { lista: [], atual: 'windows' };
let emChamada = false;
const REPO = path.join(VOZ, '..');
const MARCA_REPARO = path.join(SINAIS, 'ultimo_reparo.json');
let quedasReparo = [];

function git(args) {
  return new Promise((resolve, reject) => execFile('git', args,
    { cwd: REPO, windowsHide: true, timeout: 30000 },
    (erro, stdout) => erro ? reject(erro) : resolve(stdout.trim())));
}

async function recuperarReparo() {
  try {
    if (!fs.existsSync(MARCA_REPARO)) return;
    const reparo = JSON.parse(fs.readFileSync(MARCA_REPARO, 'utf8'));
    if (!/^[a-f0-9]{40}$/.test(reparo.commit)) return;
    quedasReparo = quedasReparo.filter((ts) => Date.now() - ts < 300000);
    quedasReparo.push(Date.now());
    if (quedasReparo.length < 2) return;
    if (await git(['status', '--porcelain']) || (await git(['branch', '--show-current'])).startsWith('reparo/')
        || await git(['rev-parse', 'HEAD']) !== reparo.commit) throw new Error('Repositório mudou após o reparo; reversão suspensa.');
    await git(['revert', '--no-edit', reparo.commit]);
    if (Number.isInteger(reparo.id)) {
      await new Promise((resolve, reject) => execFile(PYTHON,
        ['-c', 'import registro,sys; registro.atualizar_bug(int(sys.argv[1]), estado="falhou")', String(reparo.id)],
        { cwd: VOZ, windowsHide: true, timeout: 30000 }, (erro) => erro ? reject(erro) : resolve()));
    }
    fs.unlinkSync(MARCA_REPARO);
    quedasReparo = [];
    if (janela) janela.webContents.send('evento', { evento: 'mensagem', autor: 'sistema',
      texto: 'O motor caiu duas vezes. Desfiz o último reparo e vou reiniciar.' });
  } catch (erro) {
    if (janela) janela.webContents.send('evento', { evento: 'erro', texto: 'Não consegui desfazer o reparo: ' + erro.message });
  }
}

function reiniciarSecretario(completo) {
  if (saindo) return;
  if (!completo) return reiniciarMotor();
  saindo = true;
  matarMotor();
  app.relaunch();
  app.exit(0);
}

function verificarReinicio() {
  const arquivo = path.join(SINAIS, 'reiniciar');
  try {
    const sinal = fs.readFileSync(arquivo, 'utf8').trim();
    fs.unlinkSync(arquivo);
    reiniciarSecretario(sinal === 'completo');
  } catch (erro) {
    if (erro.code !== 'ENOENT') console.error('Não foi possível ler o sinal de reinício:', erro);
  }
}

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
    { label: 'Motor', submenu: motores.lista.map((item) => ({
      label: item.rotulo, type: 'radio', checked: item.nome === motores.atual,
      enabled: item.disponivel, toolTip: item.motivo || '',
      click: () => enviarAoMotor({ cmd: 'motor', valor: item.nome }),
    })) },
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
  emChamada = false;
  motor = spawn(PYTHON, ['assistente_voz.py', '--ipc'], {
    cwd: VOZ, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
  });
  const estavel = setTimeout(async () => {
    try {
      if (!await git(['status', '--porcelain']) && !(await git(['branch', '--show-current'])).startsWith('reparo/')) {
        await git(['tag', '-f', 'estavel']);
        if (fs.existsSync(MARCA_REPARO)) fs.unlinkSync(MARCA_REPARO);
      }
    } catch (erro) { console.error('Não consegui marcar a versão estável:', erro); }
  }, 30 * 60 * 1000);
  readline.createInterface({ input: motor.stdout }).on('line', (linha) => {
    let ev;
    try { ev = JSON.parse(linha); } catch { return; }
    if (ev.evento === 'ponte') ponte = { ...ev, qr: ev.ativa ? (ev.qr === undefined ? ponte.qr : ev.qr) : null };
    if (ev.evento === 'reparo') {
      fs.mkdirSync(SINAIS, { recursive: true });
      fs.writeFileSync(MARCA_REPARO, JSON.stringify({ commit: ev.commit, id: ev.id }));
      quedasReparo = [];
    }
    if (ev.evento === 'microfone') emChamada = Boolean(ev.app);
    if (ev.evento === 'motores') { motores = { lista: ev.lista, atual: ev.atual }; atualizarBandeja(); }
    if (ev.evento === 'vozes') vozes = { lista: ev.lista, atual: ev.atual };
    if (ev.evento === 'reiniciar') reiniciarSecretario(ev.completo === true);
    if (ev.evento === 'estado') { estadoAtual = ev.estado; atualizarBandeja(); }
    if (ev.origem !== 'celular' && (ev.evento === 'resposta_silenciosa' || (ev.evento === 'mensagem' && ev.autor === 'secretario' && janela && !janela.isVisible() && !emChamada))) {
      const n = new Notification({ title: 'Secretário', body: ev.texto.slice(0, 200), icon: path.join(ICONES, 'app.png') });
      n.on('click', mostrar);
      n.show();
    }
    if (janela) janela.webContents.send('evento', ev);
  });
  let erros = '';
  motor.stderr.on('data', (d) => { erros = (erros + d.toString()).split(/\r?\n/).slice(-50).join('\n').slice(-32000); });
  motor.on('exit', async (codigo) => {
    clearTimeout(estavel);
    const queda = !saindo && !reiniciando;
    if (queda) {
      fs.mkdirSync(SINAIS, { recursive: true });
      fs.writeFileSync(path.join(SINAIS, 'bug_' + Date.now() + '.json'),
        JSON.stringify({ codigo, stderr: erros }));
      await recuperarReparo();
    }
    motor = null;
    ponte = { ativa: false, aparelhos: [] };
    if (janela) janela.webContents.send('evento', { evento: 'ponte', ...ponte });
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

let verificandoInstalacao = false;
function verificarInstalacao(manual) {
  if (verificandoInstalacao) return;
  verificandoInstalacao = true;
  execFile(PYTHON, [path.join(VOZ, 'diagnostico.py'), '--instalacao', '--json'],
    { cwd: REPO, windowsHide: true, timeout: 30000 }, async (erro, stdout) => {
      verificandoInstalacao = false;
      let faltas;
      try { faltas = JSON.parse(stdout).filter((l) => l.estado !== 'ok' && !l.opcional); }
      catch { faltas = [{ passo: 'Diagnóstico indisponível: confira o Python do venv.' }]; }
      if (!manual && !faltas.length) return;
      const escolha = await dialog.showMessageBox(janela, {
        type: faltas.length ? 'warning' : 'info', title: 'Verificar instalação',
        message: faltas.length ? 'Há passos pendentes na instalação.' : 'Instalação verificada.',
        detail: faltas.map((l) => l.passo).join('\n'),
        buttons: faltas.length ? ['Fechar', 'Executar instalador…'] : ['Fechar'], cancelId: 0,
      });
      if (escolha.response !== 1) return;
      const confirmar = await dialog.showMessageBox(janela, {
        type: 'question', message: 'Instalar os componentes que faltam?',
        detail: 'O instalador pode baixar programas e solicitar permissões do Windows.',
        buttons: ['Cancelar', 'Instalar'], defaultId: 0, cancelId: 0,
      });
      if (confirmar.response === 1) {
        const processo = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass',
          '-File', path.join(REPO, 'instalacao', 'instalar.ps1')], { cwd: REPO, windowsHide: true });
        processo.on('error', (e) => dialog.showErrorBox('Instalação', e.message));
        processo.on('close', () => verificarInstalacao(true));
      }
    });
}

ipcMain.on('cmd', (_e, cmd) => {
  if (cmd.cmd === 'verificar-instalacao') return verificarInstalacao(true);
  if (cmd.cmd === 'mudo') return alternarMudo(cmd.valor);
  if (cmd.cmd === 'obsidian') return abrirObsidian();
  if (cmd.cmd === 'ponte' && (!motor || !motor.stdin.writable)) {
    if (janela) janela.webContents.send('evento', {
      evento: 'ponte', ativa: false, aparelhos: [], erro: 'Aguarde o motor iniciar.'
    });
    return;
  }
  enviarAoMotor(cmd);
});
ipcMain.handle('estado', () => ({ estado: estadoAtual, mudo, motores, vozes, ponte }));

app.whenReady().then(() => {
  app.setAppUserModelId('Secretario.Deivid');
  criarJanela();
  janela.webContents.once('did-finish-load', () => verificarInstalacao(false));
  bandeja = new Tray(nativeImage.createFromPath(path.join(ICONES, 'app.png')).resize({ width: 16, height: 16 }));
  bandeja.on('click', mostrar);
  atualizarBandeja();
  iniciarMotor();
  fs.mkdirSync(SINAIS, { recursive: true });
  const vigia = fs.watch(SINAIS, (_evento, arquivo) => {
    if (!arquivo || arquivo.toString() === 'reiniciar') verificarReinicio();
  });
  vigia.on('error', (erro) => console.error('Não foi possível vigiar os sinais:', erro));
  app.on('will-quit', () => vigia.close());
  verificarReinicio();
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
