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

---

# Fase 2 — memória por assuntos, SQLite, reinício, troca de motor, Gemma usando o PC

Regra extra: o Python do venv NÃO roda no sandbox do Codex. Escreva o código e os testes;
quem roda a verificação é o revisor. Testes nunca podem usar microfone, câmera, tela,
Ollama de verdade nem o cofre real: use `tmp_path` e funções falsas (injeção/monkeypatch).

## Convenções do cofre (valem para T8, T9, T12, T16)
Cofre: `Path.home() / "Documents" / "Secretario"` (sempre aceitar `cofre=` como parâmetro).
- `Assuntos/<Assunto>.md` — nota-hub. Lista FIXA de assuntos (constante `ASSUNTOS` em
  `memoria.py`): Religião, Trabalho, Família, Finanças, Saúde, Tecnologia, Estudos,
  Compromissos, Casa, Lazer, Pessoas, Outros. Formato:
  ```
  ---
  tipo: assunto
  atualizado: AAAA-MM-DD
  ---
  # Religião

  ## Conceitos
  - [[Jesus Cristo]] — resumo de uma linha
  ```
- `Conceitos/<Nome>.md` — uma nota por conceito, nome com iniciais maiúsculas. Formato:
  ```
  ---
  tipo: conceito
  assunto: "[[Religião]]"
  aliases: [Jesus, Cristo]
  atualizado: AAAA-MM-DD
  ---
  # Jesus Cristo

  Resumo em 1–3 frases.

  ## Relacionados
  - [[Bíblia]]

  ## Das conversas
  - AAAA-MM-DD — fato curto dito pelo Deivid
  ```
- `Perfil/Aprendizados.md` — fatos sobre o usuário: `- AAAA-MM-DD — fato`.
- `Diário/AAAA-MM-DD.md` — `- HH:MM — **Você:** pergunta → **Secretário:** resposta` (cada
  lado cortado em 300 caracteres).
- Índice de busca: `<cofre>/.secretario/indice.json` (pasta oculta, não aparece no Obsidian).

## T8 — Memória: preparar cofre, indexar, buscar, contexto
- Arquivos: criar `voz/memoria.py` e `voz/tests/test_memoria.py`.
- Fazer (só biblioteca padrão; use `comum.normalizar` para comparar textos):
  - `preparar_cofre(cofre=COFRE)`: cria `Assuntos/` com uma nota-hub para cada item de
    `ASSUNTOS` (só se não existir), cria `Conceitos/` e `.secretario/`. Idempotente.
  - `ler_nota(caminho) -> dict`: `titulo` (nome do arquivo sem .md), `frontmatter` (subconjunto
    de YAML: `chave: valor`, listas `[a, b]` e listas com `- item`; aspas removidas),
    `links` (alvos de `[[x]]` e `[[x|y]]`, sem duplicatas), `resumo` (primeiro parágrafo de
    texto após o título `# `, até 200 caracteres).
  - `indexar(cofre=COFRE) -> dict`: lê todos os `.md` (exceto `Modelos/` e pastas ocultas) e
    grava `.secretario/indice.json` com `{"notas": [{caminho (relativo, com /), titulo, tipo,
    assunto (sem [[ ]]), aliases, links, resumo}], "termos": {termo_normalizado: [caminhos]}}`,
    onde os termos são o título e os aliases normalizados.
  - `buscar(texto, cofre=COFRE, limite=5) -> list[dict]`: carrega o índice (indexa se não
    existir). Pontuação: termo (título/alias) que aparece em `normalizar(texto)` como palavra(s)
    inteira(s) = 3 pontos; cada palavra do texto com 4+ letras que não é stopword e aparece no
    título/alias = 1 ponto. Depois acrescenta, com metade da pontuação, o hub do assunto e os
    `links` das notas encontradas (1 salto). Retorna os `limite` maiores, cada um com
    `caminho, titulo, assunto, resumo, pontos`.
  - `contexto(texto, cofre=COFRE, max_chars=1200) -> str`: "" se nada encontrado; senão
    `"Memória relevante (cofre Obsidian):\n- Jesus Cristo [Religião]: resumo. Ligado a: Bíblia"`
    uma linha por nota, cortando em `max_chars`.
- Testes: preparar_cofre idempotente; ler_nota com frontmatter nas duas formas de lista;
  buscar("o que a bíblia fala de jesus") encontra Jesus Cristo e Bíblia e traz o hub Religião;
  texto sem relação retorna lista vazia; contexto respeita max_chars.

## T9 — Memória: aprender e diário
- Arquivos: `voz/memoria.py`, `voz/tests/test_memoria.py`.
- Fazer:
  - `aprender(conhecimento: dict, cofre=COFRE, hoje=None) -> list[str]` (devolve caminhos
    alterados). Entrada:
    `{"conceitos": [{"nome", "assunto", "resumo", "aliases": [], "relacionados": [], "fato"}],
      "fatos_usuario": ["..."]}`.
    Para cada conceito: assunto fora de `ASSUNTOS` vira "Outros"; procura nota existente pelo
    nome OU alias (normalizados) em `Conceitos/`; se não existe, cria no formato das convenções;
    se existe, une aliases e relacionados sem duplicar, acrescenta o `fato` (se houver e não for
    repetido) em "## Das conversas" e atualiza `atualizado:`; não apaga o resumo existente.
    Garante a linha `- [[Nome]] — resumo` no hub do assunto (sem duplicar). Relacionados que
    não existem viram notas mínimas no mesmo assunto (assim o grafo fica ligado).
    `fatos_usuario` vão para `Perfil/Aprendizados.md` sem repetir.
  - `registrar_diario(pergunta, resposta, cofre=COFRE, agora=None)`: acrescenta a linha no
    `Diário/AAAA-MM-DD.md` (cria com título `# AAAA-MM-DD` se não existir).
  - Ao final de `aprender`, chama `indexar(cofre)`.
- Testes: criar conceito novo cria nota + linha no hub; aprender de novo com alias diferente
  não duplica nota; relacionado inexistente vira nota mínima; assunto inválido vai para Outros;
  diário acumula linhas no mesmo dia.

## T10 — Log em SQLite
- Arquivos: criar `voz/registro.py` e `voz/tests/test_registro.py`; alterar `voz/assistente_voz.py`
  (só a função `registrar` e os métodos `tarefa`/`tarefa_local` para chamar as funções novas).
- Fazer (módulo `sqlite3` da biblioteca padrão; banco `voz/secretario.db`, aceitar `banco=`):
  - Tabelas: `eventos(id INTEGER PK, ts TEXT, autor TEXT, texto TEXT, sessao TEXT, motor TEXT)`
    e `tarefas(id INTEGER PK, inicio TEXT, fim TEXT, comando TEXT, motor TEXT, status TEXT,
    ferramentas TEXT, resposta TEXT, duracao_ms INTEGER)`. Criar com `IF NOT EXISTS`; modo WAL.
  - `evento(autor, texto, sessao=None, motor=None)`; `inicio_tarefa(comando, motor) -> id`;
    `fim_tarefa(id, status, resposta="", ferramentas=())` (status: ok | erro | cancelada);
    `ultimas_tarefas(n=20) -> list[dict]`. Uma conexão por chamada (seguro entre threads).
  - `registrar` em `assistente_voz.py` continua escrevendo o `.txt` e também chama `evento`.
    `tarefa` e `tarefa_local` abrem/fecham a linha em `tarefas` com status e nomes das ferramentas.
  - Adicionar `voz/secretario.db*` ao `.gitignore`.
- Testes: cria tabelas em banco temporário; ciclo inicio→fim grava duração e status;
  `ultimas_tarefas` ordena da mais nova para a mais antiga.

## T11 — Catálogo de ações locais (para o Gemma)
- Arquivos: criar `voz/acoes.py` e `voz/tests/test_acoes.py`; em `voz/sentidos_mcp.py` extrair
  `salvar_tela(monitor=1) -> Path` e `salvar_foto(camera=0) -> Path` (as ferramentas MCP
  `captura_tela`/`foto_camera` passam a usar essas funções; comportamento igual).
- Fazer: dicionário `ACOES = {nome: {"funcao", "descricao", "args": {arg: descrição},
  "confirmar": bool}}` com: `abrir(alvo)`, `abrir_pasta(nome)` (aceita documentos, downloads,
  área de trabalho, imagens, músicas, vídeos ou caminho), `pesquisar_web(consulta)` (abre o
  navegador padrão em `https://www.google.com/search?q=...`), `ver_tela()` e `foto_camera()`
  (retornam o caminho da imagem), `clicar(x, y)`, `digitar(texto, enter=False)`,
  `teclas(combinacao)`, `rolar(quantidade)`, `janelas()`, `focar_janela(titulo)`,
  `comando(powershell)`, `lembrete(quando, texto)`. Reaproveite as funções de `sentidos_mcp`.
  - `comando_seguro(cmd) -> bool` só aceita leitura: começa com um de `Get-ChildItem,
    Get-Date, Get-Process, Get-ComputerInfo, Get-Volume, Get-NetIPAddress, Get-Clipboard,
    Test-Path, Get-Content` e só encadeia com barra vertical para `Select-Object, Where-Object,
    Sort-Object, Measure-Object, Format-Table, Format-List`; rejeita ponto e vírgula, `&`, `>`,
    crase, `$(`, `Invoke-`, `Remove-`, `Set-`, `Stop-`, `Start-`. Comando seguro roda direto
    (`powershell -NoProfile -Command`, timeout 20 s, saída cortada em 1500 caracteres);
    comando não seguro é tratado como `"confirmar": True` (quem chama decide).
  - `executar(nome, args, pedido="") -> dict` valida nome/args, recusa `foto_camera` se
    `normalizar(pedido)` não contém "camera", "foto" ou "selfie", e devolve sempre
    `{"ok": bool, "texto": str, "imagem": caminho ou None}` (nunca lança exceção).
  - `precisa_confirmar(nome, args) -> bool`; `descrever_acoes() -> str` (lista compacta para o prompt).
- Testes: `comando_seguro` aceita/rejeita casos típicos; `executar` com nome inexistente
  devolve ok False; foto sem pedir é recusada; `descrever_acoes` cita todas as ações
  (use monkeypatch para não abrir nada de verdade; não importe nada que abra câmera/microfone).

## T12 — Extrator de conhecimento com o Gemma local
- Arquivos: criar `voz/extrator.py` e `voz/tests/test_extrator.py`.
- Fazer: `extrair(pergunta, resposta, chamar=None) -> dict` que monta um prompt pedindo JSON
  no formato de entrada de `memoria.aprender` (lista `memoria.ASSUNTOS` no prompt; instrução:
  só conceitos realmente tratados, no máximo 5; fatos_usuario só sobre o Deivid; nada se for
  conversa trivial; exemplo: Jesus Cristo → Religião, relacionado a Bíblia). `chamar(mensagens)
  -> str` padrão faz POST em `http://localhost:11434/api/chat` com `{"model": "gemma3:4b",
  "format": "json", "stream": false, "keep_alive": "30m", "options": {"temperature": 0.1}}`
  (urllib, timeout 120 s). Valida e limpa a saída: descarta itens sem `nome`, corta textos
  longos, garante as chaves; qualquer erro (Ollama fechado, JSON inválido) devolve
  `{"conceitos": [], "fatos_usuario": []}`.
- Testes: com `chamar` falso devolvendo JSON válido, inválido e com campos faltando.

## T13 — Agente local (Gemma usa o computador)
- Arquivos: criar `voz/agente_local.py` e `voz/tests/test_agente_local.py`.
- Fazer: `executar(pedido, historico=None, memoria="", chamar=None, max_passos=6) -> dict`.
  - Prompt de sistema: secretário pessoal do Deivid, em português, respostas curtas para voz;
    lista de `acoes.descrever_acoes()`; o texto `memoria`; formato de saída obrigatório, um JSON
    por vez: `{"acao": "<nome>", "args": {...}}` ou `{"acao": "responder", "texto": "..."}`.
  - Laço: chama o modelo (`chamar(mensagens, imagens=None) -> str`; o padrão usa `/api/chat`
    do Ollama com `format: "json"`, `options.temperature 0.2`, `num_ctx 4096`, e manda imagens
    em base64 no campo `images` da última mensagem). Executa com `acoes.executar(nome, args,
    pedido)` e devolve o resultado ao modelo como mensagem do usuário
    `"Resultado de <acao>: <texto>"` (com a imagem, se houver). Para em `responder`.
  - Se `acoes.precisa_confirmar(nome, args)`: NÃO executa; devolve
    `{"texto": "Posso <descrição curta>?", "pendente": {"acao", "args", "pedido"}, "passos": [...]}`.
  - `confirmar(pendente) -> dict` executa a ação pendente e devolve `{"texto", "pendente": None, "passos"}`.
  - Esgotou `max_passos` ou JSON inválido 2 vezes seguidas: responde
    "Não consegui concluir sozinho. Diga: secretário, usar Claude." Nunca lança exceção.
  - Retorno normal: `{"texto": str, "pendente": None, "passos": [nomes das ações]}`.
- Testes com `chamar` falso roteirizado e `acoes.executar` falso: responde direto; abre algo
  e depois responde; comando perigoso vira pendente; JSON inválido repetido cai na mensagem de
  desistência; ver_tela manda a imagem na próxima chamada.

## T14 — Reinício sob comando
- Arquivos: `voz/assistente_voz.py`, `voz/sentidos_mcp.py`, `app/main.js`, `voz/voz_prompt.md`.
- Fazer:
  - Voz: "secretário, reinicia" / "reiniciar" → fala "Reiniciando.", emite
    `{"evento":"reiniciar","completo":false}` e encerra. "reinicia tudo" / "reiniciar o app"
    → `completo: true`.
  - Sinal por arquivo: ferramenta MCP `reiniciar_secretario(completo: bool = False)` cria
    `voz/sinais/reiniciar` com o texto `completo` ou `motor`. No `main.js`, vigiar a pasta
    (`fs.watch`, criar se não existir); ao ver o arquivo: apaga e reinicia.
  - `main.js`: evento/sinal de motor → `reiniciarMotor()` (já existe); completo →
    `matarMotor(); app.relaunch(); app.exit(0)`.
  - Em `assistente_voz.py`, cancelar/sair matam a árvore do processo do claude:
    `subprocess.run(["taskkill", "/pid", str(pid), "/T", "/F"])` em vez de `proc.kill()`.
  - `voz_prompt.md`: uma linha dizendo que, para se reiniciar, use `reiniciar_secretario`.
  - Adicionar `voz/sinais/` ao `.gitignore`.
- Verificação: `node --check app/main.js`; `py_compile` dos .py; testes existentes passam.

## T15 — Troca de motor pela interface
- Arquivos: `voz/assistente_voz.py`, `app/main.js`, `app/renderer.js`, `app/index.html`, `app/estilo.css`.
- Fazer:
  - Motor emite `{"evento":"motor","motor":"claude"|"gemma"}` ao iniciar e ao trocar; aceita
    `{"cmd":"motor","valor":"claude"|"gemma"}` (usa `trocar_motor`, que já existe).
  - Interface: no topo do chat, à esquerda da pílula de estado, um seletor segmentado com
    "Claude · nuvem" e "Gemma · local" (mesmo estilo de `.pilula`; item ativo com `--degrade`
    e texto escuro).
  - Bandeja: dois itens `type: 'radio'` "Motor: Claude (nuvem)" / "Motor: Gemma (local)".
- Verificação: `node --check` nos .js; `py_compile`.

## T16 — Ligar a memória ao motor
- Arquivos: `voz/assistente_voz.py`, `voz/voz_prompt.md`.
- Fazer: na inicialização, `memoria.preparar_cofre()` e `memoria.indexar()` (try/except, nunca
  derrubar o motor). Antes de cada tarefa (os dois motores), `ctx = memoria.contexto(comando)`;
  se não vazio, o Claude recebe `ctx + "\n\nPedido: " + comando`; o Gemma recebe `ctx` no
  prompt de sistema. Depois de cada resposta, numa thread daemon:
  `memoria.registrar_diario` → `extrator.extrair` → `memoria.aprender`, e emite
  `{"evento":"memoria","notas":[caminhos]}` se algo mudou. Erros só vão para o log.
  `voz_prompt.md`: explicar que o contexto de memória já vem no pedido e que fatos novos são
  gravados automaticamente (não precisa reler o cofre inteiro a cada pedido).
- Verificação: `py_compile`; testes existentes passam.

## T17 — Gemma com ações no modo local
- Arquivos: `voz/assistente_voz.py`.
- Fazer: `tarefa_local` passa a usar `agente_local.executar(comando, historico, memoria=ctx)`
  em vez da conversa pura. Emite `{"evento":"ferramenta","nome":...}` para cada passo. Se vier
  `pendente`, guarda em `self.pendente` e fala a pergunta; o próximo comando que começar com
  "sim", "pode", "confirmo" executa `agente_local.confirmar`; qualquer outro descarta a
  pendência. Atualizar `PROMPT_LOCAL` (agora ele pode usar o computador).
- Verificação: `py_compile`; testes existentes passam.
