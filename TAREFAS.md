# Backlog do Secretário — tarefas para o Codex

Regras para quem executa (Codex):
- Faça SOMENTE a tarefa indicada. Não refatore nem renomeie nada fora dos arquivos listados.
- Siga o estilo do código existente: nomes e comentários em português, mesma densidade de comentários.
- Python roda em `voz/.venv/Scripts/python.exe`. Não instale pacotes novos, a não ser que a tarefa permita.
- Não rode o app nem o motor de voz (usam microfone); rode só o comando de verificação da tarefa.
- Ao terminar, responda: arquivos alterados + resultado do comando de verificação.

Arquitetura (resumo): `voz/assistente_voz.py` (motor: microfone → Whisper → `claude -p`,
fala em `--ipc` com JSON por linha no stdin/stdout) · `voz/comum.py` (microfone, transcrição,
fala) · `voz/sentidos_mcp.py` (servidor MCP: tela, mouse, teclado, câmera) ·
`app/main.js` (Electron: bandeja, motor, atalhos) · `app/renderer.js` + `index.html` +
`estilo.css` (chat estilo Discord) · `app/preload.js` (ponte IPC).

---

## T1 — Testes das funções puras
- Arquivos: criar `voz/tests/test_comum.py`.
- Fazer: testes pytest para `normalizar`, `texto_para_fala` (remove markdown, troca URL por
  "link", corta texto > 700 caracteres terminando em "Os detalhes estão na tela.") e para a
  regex `ATIVACAO` de `assistente_voz.py` ("Secretário, abre", "secretaria abre", "SECRETARIO:
  x" casam; "secretariado" não casa). Importar `assistente_voz` sem abrir microfone (só a regex
  é usada no nível do módulo — se o import tiver efeitos colaterais, testar uma cópia da regex
  não é aceito; em vez disso, avise).
- Pode instalar: `pytest` no venv.
- Verificação: `voz/.venv/Scripts/python -m pytest voz/tests -q` → todos passam.

## T2 — Arquivo de configuração
- Arquivos: criar `voz/config.py` e `voz/config.exemplo.json`; alterar `voz/comum.py`.
- Fazer: `config.py` com `carregar()` que lê `voz/config.json` (se existir) e completa com
  padrões: `{"microfone": null, "modelo_whisper": "small", "velocidade_fala": 190,
  "janela_conversa": 15, "palavra_ativacao": "secretário"}`. Em `comum.py`, trocar as leituras
  de `os.environ` (SECRETARIO_MIC, SECRETARIO_WHISPER, SECRETARIO_VELOCIDADE_FALA) por
  `config.carregar()`, mantendo a variável de ambiente como prioridade se estiver definida.
- Verificação: `voz/.venv/Scripts/python -c "import sys; sys.path.insert(0,'voz'); import config; print(config.carregar())"`.

## T3 — Botões Sim / Não para confirmações
- Arquivos: `app/renderer.js`, `app/estilo.css`.
- Fazer: quando chegar uma mensagem do secretário cujo texto termina com "?", mostrar abaixo
  dela dois botões "Sim" e "Não". Clicar envia `{cmd:"texto", texto:"sim"}` (ou "não"),
  adiciona a mensagem do usuário no chat e remove os botões. Botões só na última mensagem.
- Verificação: `node --check app/renderer.js`.

## T4 — Nível do microfone (barra de volume)
- Arquivos: `voz/comum.py`, `voz/assistente_voz.py`, `app/renderer.js`, `app/index.html`, `app/estilo.css`.
- Fazer: `Microfone` guarda o último `rms` em `self.nivel`. No modo `--ipc`, uma thread emite
  `{"evento":"nivel","valor":<0..1>}` a cada 150 ms (valor = min(1, nivel/limiar/4)).
  No painel do usuário, uma barra fina abaixo do nome mostra o nível (verde).
- Verificação: `node --check app/renderer.js` e
  `voz/.venv/Scripts/python -m py_compile voz/comum.py voz/assistente_voz.py`.

## T5 — Lembretes
- Arquivos: `voz/sentidos_mcp.py`, `app/main.js`.
- Fazer: ferramenta MCP `lembrete(quando: str, texto: str)` — `quando` em ISO
  "AAAA-MM-DDTHH:MM" — que acrescenta `{quando, texto, feito:false}` em
  `voz/lembretes.json`; e `listar_lembretes()`. No `main.js`, a cada 30 s ler o arquivo e,
  para lembretes vencidos e não feitos, mostrar `Notification` e marcar `feito:true`.
- Verificação: `node --check app/main.js` e
  `voz/.venv/Scripts/python -m py_compile voz/sentidos_mcp.py`.

## T6 — Rotação do log
- Arquivos: `voz/assistente_voz.py`.
- Fazer: em `registrar`, se `log_voz.txt` passar de 1 MB, renomear para `log_voz.1.txt`
  (substituindo o anterior) antes de escrever.
- Verificação: `voz/.venv/Scripts/python -m py_compile voz/assistente_voz.py`.

## T7 — Instalador do app
- Arquivos: `app/package.json`.
- Fazer: adicionar `electron-builder` (versão fixa) e script `"dist"` gerando instalador NSIS
  para Windows com `productName` "Secretário", ícone `icones/app.png`, `appId`
  "secretario.deivid". Não mover arquivos.
- Pode instalar: `electron-builder` via npm.
- Verificação: `npm run dist` em `app/` gera um `.exe` em `app/dist/`.
