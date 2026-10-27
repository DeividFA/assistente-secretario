// Converte os ícones SVG de app/icones em PNG (a bandeja do Windows precisa de PNG).
// Uso: electron ferramentas/gerar-icones.js

const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const PASTA = path.join(__dirname, '..', 'icones');
const TAMANHO = 256;

app.whenReady().then(async () => {
  const janela = new BrowserWindow({ width: TAMANHO, height: TAMANHO, show: false, frame: false, transparent: true,
    webPreferences: { offscreen: true } });
  for (const arquivo of fs.readdirSync(PASTA).filter((a) => a.endsWith('.svg'))) {
    const svg = fs.readFileSync(path.join(PASTA, arquivo), 'utf8');
    const html = `<html><body style="margin:0;background:transparent"><img style="width:${TAMANHO}px;height:${TAMANHO}px;display:block"
      src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}"></body></html>`;
    await janela.loadURL('data:text/html;base64,' + Buffer.from(html).toString('base64'));
    await new Promise((r) => setTimeout(r, 150));
    const imagem = await janela.webContents.capturePage({ x: 0, y: 0, width: TAMANHO, height: TAMANHO });
    fs.writeFileSync(path.join(PASTA, arquivo.replace('.svg', '.png')), imagem.resize({ width: TAMANHO, height: TAMANHO }).toPNG());
    console.log('gerado', arquivo.replace('.svg', '.png'));
  }
  app.quit();
});
