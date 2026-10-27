// Interface do chat: conversas salvas localmente, mensagens e estado do motor de voz.

const $ = (id) => document.getElementById(id);
const ROTULOS = { carregando: 'carregando…', ouvindo: 'ouvindo — diga “Secretário…”', escutando: 'escutando você',
  pensando: 'trabalhando', falando: 'falando', mudo: 'microfone mudo', parado: 'motor parado' };

let dados = carregar();
let silencio = false;

function carregar() {
  try {
    const d = JSON.parse(localStorage.getItem('conversas'));
    if (d && d.lista.length) return d;
  } catch {}
  return { lista: [novaConversa()], atual: 0 };
}
function salvar() { try { localStorage.setItem('conversas', JSON.stringify(dados)); } catch {} }
function novaConversa() { return { titulo: 'geral', sessao: null, mensagens: [] }; }
function atual() { return dados.lista[dados.atual]; }

function escapar(t) { return t.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function formatar(t) {
  return escapar(t)
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre>$2</pre>')
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank">$2</a>');
}
const hora = (ts) => new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });

function desenharConversas() {
  const ul = $('conversas');
  ul.innerHTML = '';
  dados.lista.forEach((c, i) => {
    const li = document.createElement('li');
    li.className = i === dados.atual ? 'ativa' : '';
    li.innerHTML = `<span class="nome">${escapar(c.titulo)}</span><button class="apagar" title="Apagar">✕</button>`;
    li.onclick = () => trocarConversa(i);
    li.querySelector('.apagar').onclick = (e) => { e.stopPropagation(); apagarConversa(i); };
    ul.appendChild(li);
  });
  $('titulo-conversa').textContent = atual().titulo;
}

function desenharMensagens() {
  const box = $('mensagens');
  box.innerHTML = `<div class="boas-vindas"><div class="avatar sec" style="width:68px;height:68px"><img src="icones/app.png" alt=""></div>
    <h1>Seu secretário</h1>
    <p>Fale “<b>Secretário,</b> …” a qualquer momento, aperte <b>Ctrl+Shift+Espaço</b> para falar direto, ou digite abaixo.</p>
    <p>Fechar a janela só esconde — ele continua no ícone da bandeja.</p></div>`;
  let anterior = null;
  for (const m of atual().mensagens) { box.appendChild(elementoMensagem(m, anterior)); anterior = m; }
  box.scrollTop = box.scrollHeight;
}

function elementoMensagem(m, anterior) {
  const div = document.createElement('div');
  if (m.autor === 'sistema' || m.autor === 'erro' || m.autor === 'ferramenta') {
    div.className = m.autor === 'ferramenta' ? 'ferramenta' : `sistema ${m.autor === 'erro' ? 'erro' : ''}`;
    div.textContent = m.texto;
    return div;
  }
  const sec = m.autor === 'secretario';
  const continua = anterior && anterior.autor === m.autor && m.ts - anterior.ts < 5 * 60e3;
  div.className = 'msg' + (continua ? ' continua' : '');
  div.innerHTML = `
    <div class="avatar ${sec ? 'sec' : 'eu'}">${sec ? '<img src="icones/app.png" alt="">' : 'D'}</div>
    <div class="corpo">
      <div class="cab">${sec ? '<span class="tag">BOT</span><strong class="sec">Secretário</strong>' : '<strong>Deivid</strong>'}
        <time>${hora(m.ts)}</time>${m.via === 'voz' ? '<span class="via">· por voz</span>' : ''}</div>
      <div class="texto">${formatar(m.texto)}</div>
    </div>`;
  return div;
}

function adicionar(m) {
  m.ts = m.ts || Date.now();
  const c = atual();
  const anterior = c.mensagens[c.mensagens.length - 1];
  c.mensagens.push(m);
  if (c.titulo === 'geral' && m.autor === 'voce') {
    c.titulo = m.texto.slice(0, 32).toLowerCase();
    desenharConversas();
  }
  salvar();
  const box = $('mensagens');
  const noFim = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  box.appendChild(elementoMensagem(m, anterior));
  if (noFim || m.autor === 'voce') box.scrollTop = box.scrollHeight;
}

function trocarConversa(i) {
  dados.atual = i;
  salvar();
  window.secretario.enviar({ cmd: 'sessao', id: atual().sessao });
  desenharConversas();
  desenharMensagens();
}
function criarConversa() {
  dados.lista.unshift(novaConversa());
  trocarConversa(0);
}
function apagarConversa(i) {
  if (!confirm(`Apagar a conversa "${dados.lista[i].titulo}"?`)) return;
  dados.lista.splice(i, 1);
  if (!dados.lista.length) dados.lista.push(novaConversa());
  trocarConversa(Math.min(dados.atual, dados.lista.length - 1));
}

function mostrarEstado(estado) {
  $('chip-estado').className = 'chip ' + estado;
  $('chip-estado').textContent = { ouvindo: 'ouvindo', escutando: 'escutando', pensando: 'trabalhando', falando: 'falando',
    mudo: 'mudo', carregando: 'carregando', parado: 'parado' }[estado] || estado;
  $('bolinha').className = 'bolinha ' + estado;
  $('estado-texto').textContent = ROTULOS[estado] || estado;
  $('digitando').hidden = estado !== 'pensando';
  $('btn-falar').classList.toggle('escutando', estado === 'escutando');
  if (estado === 'pensando') $('digitando-texto').textContent = 'Secretário está trabalhando…';
}

window.secretario.aoEvento((ev) => {
  switch (ev.evento) {
    case 'estado': mostrarEstado(ev.estado); break;
    case 'mudo': $('btn-mudo').classList.toggle('desligado', ev.valor); break;
    case 'mensagem':
      if (ev.autor === 'voce' && ev.via !== 'texto') adicionar({ autor: 'voce', texto: ev.texto, via: 'voz' });
      else if (ev.autor !== 'voce') adicionar({ autor: ev.autor, texto: ev.texto });
      break;
    case 'ferramenta':
      $('digitando-texto').textContent = `Secretário está trabalhando… (${ev.nome})`;
      adicionar({ autor: 'ferramenta', texto: ev.nome });
      break;
    case 'sessao': atual().sessao = ev.id; salvar(); break;
    case 'nova_conversa': criarConversa(); break;
    case 'erro': adicionar({ autor: 'erro', texto: ev.texto }); break;
  }
});

$('form').onsubmit = (e) => {
  e.preventDefault();
  const texto = $('texto').value.trim();
  if (!texto) return;
  adicionar({ autor: 'voce', texto, via: 'texto' });
  window.secretario.enviar({ cmd: 'texto', texto });
  $('texto').value = '';
  $('texto').style.height = '';
};
$('texto').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('form').requestSubmit(); }
});
$('texto').addEventListener('input', (e) => { e.target.style.height = ''; e.target.style.height = e.target.scrollHeight + 'px'; });
$('btn-nova').onclick = criarConversa;
$('btn-cancelar').onclick = () => window.secretario.enviar({ cmd: 'cancelar' });
$('btn-falar').onclick = () => { window.secretario.enviar({ cmd: 'ouvir_agora' }); mostrarEstado('escutando'); };
$('btn-mudo').onclick = () => window.secretario.enviar({ cmd: 'mudo', valor: !$('btn-mudo').classList.contains('desligado') });
$('btn-silencio').onclick = () => {
  silencio = !silencio;
  $('btn-silencio').classList.toggle('desligado', silencio);
  window.secretario.enviar({ cmd: 'silencio', valor: silencio });
};
$('btn-obsidian').onclick = () => window.secretario.enviar({ cmd: 'obsidian' });

desenharConversas();
desenharMensagens();
window.secretario.estado().then(({ estado, mudo }) => {
  mostrarEstado(estado);
  $('btn-mudo').classList.toggle('desligado', mudo);
  window.secretario.enviar({ cmd: 'sessao', id: atual().sessao });
});
