// Interface do chat: conversas salvas localmente, mensagens e estado do motor de voz.

const $ = (id) => document.getElementById(id);
const ESTADOS = {
  carregando: ['Carregando', 'preparando o reconhecimento de voz'],
  ouvindo: ['Ouvindo', 'diga “Secretário, …”'],
  escutando: ['Escutando você', 'pode falar'],
  pensando: ['Trabalhando', 'executando sua tarefa'],
  falando: ['Falando', 'respondendo em voz alta'],
  mudo: ['Microfone mudo', 'clique em Microfone para ativar'],
  parado: ['Motor parado', 'reiniciando…'],
};
const ICONES = {
  conversa: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
  apagar: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  app: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18"/></svg>',
  busca: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  sino: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>',
  tela: '<svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
};
const SUGESTOES = [
  { icone: 'app', titulo: 'Abrir um programa', texto: 'Abre a calculadora pra mim' },
  { icone: 'busca', titulo: 'Pesquisar na web', texto: 'Pesquisa a previsão do tempo para amanhã' },
  { icone: 'sino', titulo: 'Criar um lembrete', texto: 'Me lembra amanhã às 9h de revisar meus e-mails' },
  { icone: 'tela', titulo: 'Olhar a tela', texto: 'Olha minha tela e me diz o que está aberto' },
];

let dados = carregar();
let silencio = false;
let tarefasFila = null;

function mostrarTrabalhando(pensando = false) {
  const rodando = tarefasFila === null ? Number(pensando) : tarefasFila.filter((t) => t.status === 'rodando').length;
  if (rodando && $('trabalhando').hidden) $('trabalhando-passo').textContent = 'entendendo o pedido';
  $('trabalhando-rotulo').textContent = `Trabalhando · ${rodando} ${rodando === 1 ? 'tarefa rodando' : 'tarefas rodando'}`;
  $('trabalhando').hidden = rodando === 0;
}

function mostrarFila(tarefas) {
  tarefasFila = tarefas.filter((t) => t.status === 'rodando' || t.status === 'pendente');
  $('painel-fila').hidden = tarefasFila.length === 0;
  $('fila-resumo').textContent = `Fila (${tarefasFila.length})`;
  const lista = $('fila-tarefas');
  lista.replaceChildren();
  const prioridades = ['Urgente', 'Alta', 'Normal', 'Baixa'];
  for (const tarefa of tarefasFila) {
    const linha = document.createElement('li');
    const rodando = tarefa.status === 'rodando';
    const prioridade = prioridades[tarefa.prioridade] ? Number(tarefa.prioridade) : 2;
    linha.innerHTML = `<span class="fila-estado ${rodando ? 'rodando' : 'pendente'}" role="img" aria-label="${rodando ? 'Rodando' : 'Pendente'}">${rodando
      ? '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-8-8"/></svg>'
      : '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>'}</span>
      <span class="fila-prioridade prioridade-${prioridade}">${prioridades[prioridade]}</span>
      <span class="fila-comando"></span><span class="fila-motor"></span>
      <button type="button" class="fila-cancelar">✕</button>`;
    const comando = linha.querySelector('.fila-comando');
    comando.textContent = tarefa.comando;
    comando.title = tarefa.comando;
    const motor = linha.querySelector('.fila-motor');
    motor.textContent = tarefa.motor || 'não informado';
    motor.title = `Motor: ${motor.textContent}`;
    const cancelar = linha.querySelector('.fila-cancelar');
    cancelar.title = `Cancelar tarefa ${tarefa.id}`;
    cancelar.setAttribute('aria-label', `Cancelar tarefa: ${tarefa.comando}`);
    cancelar.onclick = () => window.secretario.enviar({ cmd: 'cancelar', id: tarefa.id });
    lista.appendChild(linha);
  }
  mostrarTrabalhando();
}

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
const maiuscula = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const titulo = (c) => (c.titulo === 'geral' ? 'Nova conversa' : maiuscula(c.titulo));
const hora = (ts) => new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
function quando(ts) {
  if (!ts) return '';
  const d = new Date(ts), hoje = new Date();
  if (d.toDateString() === hoje.toDateString()) return hora(ts);
  const ontem = new Date(hoje); ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === ontem.toDateString()) return 'ontem';
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}
function saudacao() {
  const h = new Date().getHours();
  return `${h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'}, Deivid`;
}

function desenharConversas() {
  const ul = $('conversas');
  ul.innerHTML = '';
  dados.lista.forEach((c, i) => {
    const ultima = [...c.mensagens].reverse().find((m) => m.autor === 'voce' || m.autor === 'secretario');
    const li = document.createElement('li');
    li.className = i === dados.atual ? 'ativa' : '';
    li.innerHTML = `
      <div class="conv-icone">${ICONES.conversa}</div>
      <div class="conv-texto">
        <div class="conv-linha"><span class="conv-titulo">${escapar(titulo(c))}</span>
          <span class="conv-quando">${quando(ultima && ultima.ts)}</span></div>
        <div class="conv-trecho">${ultima ? escapar((ultima.autor === 'secretario' ? '' : 'Você: ') + ultima.texto) : 'Sem mensagens ainda'}</div>
      </div>
      <button class="apagar" title="Apagar conversa">${ICONES.apagar}</button>`;
    li.onclick = () => trocarConversa(i);
    li.querySelector('.apagar').onclick = (e) => { e.stopPropagation(); apagarConversa(i); };
    ul.appendChild(li);
  });
  $('titulo-conversa').textContent = titulo(atual());
}

function desenharMensagens() {
  const box = $('mensagens');
  box.innerHTML = '';
  let anterior = null;
  for (const m of atual().mensagens) { renderizar(m, anterior); anterior = m; }
  $('vazio').hidden = atual().mensagens.length > 0;
  $('saudacao').textContent = saudacao();
  rolarParaFim();
}

function renderizar(m, anterior) {
  const box = $('mensagens');
  if (m.autor === 'ferramenta') {
    // Passos consecutivos viram uma linha de etiquetas.
    let passos = box.lastElementChild;
    if (!passos || !passos.classList.contains('passos')) {
      passos = document.createElement('div');
      passos.className = 'passos';
      box.appendChild(passos);
    }
    const passo = document.createElement('span');
    passo.className = 'passo';
    passo.textContent = m.texto;
    passos.appendChild(passo);
    return;
  }
  box.appendChild(elementoMensagem(m, anterior));
}

function elementoMensagem(m, anterior) {
  const div = document.createElement('div');
  if (m.autor === 'sistema' || m.autor === 'erro') {
    div.className = `sistema ${m.autor === 'erro' ? 'erro' : ''}`;
    div.textContent = m.texto;
    return div;
  }
  const sec = m.autor === 'secretario';
  const continua = anterior && anterior.autor === m.autor && m.ts - anterior.ts < 5 * 60e3;
  div.className = `msg ${sec ? 'sec' : 'eu'}${continua ? ' continua' : ''}`;
  div.innerHTML = `
    <div class="avatar ${sec ? 'sec' : 'eu'}">${sec ? '<img src="icones/app.svg" alt="">' : 'D'}</div>
    <div class="corpo">
      <div class="cab">${sec ? '<strong class="sec">Secretário</strong>' : '<strong>Deivid</strong>'}
        <time>${hora(m.ts)}</time>${m.via === 'voz' ? '<span class="via">· por voz</span>' : ''}</div>
      <div class="texto">${formatar(m.texto)}</div>
    </div>`;
  if (sec && m.texto.trimEnd().endsWith('?') && m === atual().mensagens[atual().mensagens.length - 1]) {
    const botoes = document.createElement('div');
    botoes.className = 'confirmacao';
    for (const rotulo of ['Sim', 'Não']) {
      const botao = document.createElement('button');
      botao.type = 'button';
      botao.textContent = rotulo;
      botao.onclick = () => enviarTexto(rotulo.toLowerCase());
      botoes.appendChild(botao);
    }
    div.querySelector('.corpo').appendChild(botoes);
  }
  return div;
}

function rolarParaFim() { const r = $('rolagem'); r.scrollTop = r.scrollHeight; }

function adicionar(m) {
  m.ts = m.ts || Date.now();
  const c = atual();
  const anterior = c.mensagens[c.mensagens.length - 1];
  c.mensagens.push(m);
  if (c.titulo === 'geral' && m.autor === 'voce') c.titulo = m.texto.slice(0, 40).toLowerCase();
  salvar();
  desenharConversas();
  const rolagem = $('rolagem');
  const noFim = rolagem.scrollHeight - rolagem.scrollTop - rolagem.clientHeight < 80;
  $('mensagens').querySelectorAll('.confirmacao').forEach((botoes) => botoes.remove());
  $('vazio').hidden = true;
  renderizar(m, anterior);
  if (noFim || m.autor === 'voce') rolarParaFim();
}

function enviarTexto(texto) {
  adicionar({ autor: 'voce', texto, via: 'texto' });
  window.secretario.enviar({ cmd: 'texto', texto });
}

function trocarConversa(i) {
  dados.atual = i;
  salvar();
  window.secretario.enviar({ cmd: 'sessao', id: atual().sessao });
  desenharConversas();
  desenharMensagens();
}
function criarConversa() {
  if (!atual().mensagens.length) return trocarConversa(dados.atual); // já está numa conversa vazia
  dados.lista.unshift(novaConversa());
  trocarConversa(0);
}
function apagarConversa(i) {
  if (!confirm(`Apagar a conversa "${titulo(dados.lista[i])}"?`)) return;
  dados.lista.splice(i, 1);
  if (!dados.lista.length) dados.lista.push(novaConversa());
  trocarConversa(Math.min(dados.atual, dados.lista.length - 1));
}

function mostrarEstado(estado) {
  const [rotulo, detalhe] = ESTADOS[estado] || [estado, ''];
  $('ponto').className = 'ponto ' + estado;
  $('estado-rotulo').textContent = rotulo;
  $('estado-detalhe').textContent = detalhe;
  $('pilula').querySelector('.ponto').className = 'ponto ' + estado;
  $('pilula-texto').textContent = rotulo.toLowerCase();
  $('cartao-voz').classList.toggle('mudo', estado === 'mudo');
  $('btn-falar').classList.toggle('escutando', estado === 'escutando');
  mostrarTrabalhando(estado === 'pensando');
  if (!$('trabalhando').hidden) rolarParaFim();
  if (estado === 'parado' || estado === 'carregando' || estado === 'mudo') mostrarNivel(0);
}

const PESOS = [0.45, 0.8, 1, 0.75, 0.5];
function mostrarNivel(valor) {
  const v = Math.max(0, Math.min(1, valor));
  document.documentElement.style.setProperty('--nivel', v.toFixed(3));
  $('ondas').querySelectorAll('i').forEach((barra, i) => {
    barra.style.height = `${4 + v * 20 * PESOS[i] * (0.75 + Math.random() * 0.5)}px`;
  });
}

let motorAtual = null;
function mostrarMotores(lista, atual) {
  motorAtual = atual;
  const seletor = $('seletor-motor');
  seletor.replaceChildren();
  for (const [tipo, rotulo] of [['cli', 'Agentes'], ['api', 'Modelos (API)']]) {
    const grupo = document.createElement('optgroup');
    grupo.label = rotulo;
    for (const motor of lista.filter((item) => item.tipo === tipo)) {
      const opcao = document.createElement('option');
      opcao.value = motor.nome;
      opcao.textContent = motor.rotulo;
      opcao.disabled = !motor.disponivel;
      opcao.title = motor.motivo || motor.rotulo;
      grupo.appendChild(opcao);
    }
    seletor.appendChild(grupo);
  }
  seletor.value = atual;
  seletor.disabled = !lista.length;
  seletor.title = lista.find((item) => item.nome === atual)?.motivo || 'Escolher motor';
}
$('seletor-motor').onchange = (e) => {
  window.secretario.enviar({ cmd: 'motor', valor: e.target.value });
  e.target.value = motorAtual;
};

window.secretario.aoEvento((ev) => {
  switch (ev.evento) {
    case 'motores': mostrarMotores(ev.lista, ev.atual); break;
    case 'fila': mostrarFila(ev.tarefas); break;
    case 'estado': mostrarEstado(ev.estado); break;
    case 'nivel': mostrarNivel(ev.valor); break;
    case 'mudo': $('btn-mudo').classList.toggle('desligado', ev.valor); break;
    case 'mensagem':
      if (ev.autor === 'voce' && ev.via !== 'texto') adicionar({ autor: 'voce', texto: ev.texto, via: 'voz' });
      else if (ev.autor !== 'voce') adicionar({ autor: ev.autor, texto: ev.texto });
      break;
    case 'ferramenta':
      $('trabalhando-passo').textContent = ev.nome;
      adicionar({ autor: 'ferramenta', texto: ev.nome });
      break;
    case 'sessao': atual().sessao = ev.id; salvar(); break;
    case 'nova_conversa': criarConversa(); break;
    case 'erro': adicionar({ autor: 'erro', texto: ev.texto }); break;
  }
});

// sugestões do estado vazio
for (const s of SUGESTOES) {
  const b = document.createElement('button');
  b.className = 'sugestao';
  b.innerHTML = `${ICONES[s.icone]}<div><strong>${s.titulo}</strong><span>“${s.texto}”</span></div>`;
  b.onclick = () => enviarTexto(s.texto);
  $('sugestoes').appendChild(b);
}

$('form').onsubmit = (e) => {
  e.preventDefault();
  const texto = $('texto').value.trim();
  if (!texto) return;
  enviarTexto(texto);
  $('texto').value = '';
  $('texto').style.height = '';
  $('btn-enviar').disabled = true;
};
$('texto').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('form').requestSubmit(); }
});
$('texto').addEventListener('input', (e) => {
  e.target.style.height = '';
  e.target.style.height = e.target.scrollHeight + 'px';
  $('btn-enviar').disabled = !e.target.value.trim();
});
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
window.secretario.estado().then(({ estado, mudo, motores }) => {
  if (motorAtual === null && motores) mostrarMotores(motores.lista, motores.atual);
  mostrarEstado(estado);
  $('btn-mudo').classList.toggle('desligado', mudo);
  window.secretario.enviar({ cmd: 'sessao', id: atual().sessao });
});
