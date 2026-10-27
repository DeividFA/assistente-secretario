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

## T18 — Fila de tarefas com prioridade (multitarefa)
- Arquivos: criar `voz/fila.py` e `voz/tests/test_fila.py`.
- Fazer (só biblioteca padrão; mesmo banco SQLite da T10, `voz/secretario.db`, aceitar `banco=`):
  - Tabela `fila(id INTEGER PK, criado TEXT, comando TEXT, prioridade INTEGER, status TEXT,
    motor TEXT, inicio TEXT, fim TEXT, resposta TEXT)`. Status: `pendente`, `rodando`,
    `concluida`, `erro`, `cancelada`. Prioridade: 0 = urgente, 1 = alta, 2 = normal, 3 = baixa.
  - `detectar_prioridade(texto) -> (prioridade, texto_limpo)`: palavras-gatilho (comparar com
    `comum.normalizar`): urgente/urgencia/agora/imediatamente → 0; primeiro/antes/rapido → 1;
    depois/quando puder/mais tarde/sem pressa → 3; senão 2. Remove do texto só o gatilho
    no começo da frase (ex.: "urgente, abre o e-mail" → "abre o e-mail").
  - `dividir_pedidos(texto, chamar=None) -> list[str]`: só tenta dividir se o texto normalizado
    contém um conector: " e tambem ", " e depois ", " alem disso ", " outra coisa ",
    " e em seguida ". Usa `chamar(mensagens) -> str` (padrão: Ollama `gemma3:4b`, `format: json`,
    como em `extrator.py`) pedindo `{"pedidos": ["...", "..."]}`; no máximo 4; se falhar ou vier
    vazio, devolve `[texto]`. Pedidos ligados entre si ("abre o e-mail e depois responde o
    primeiro") devem continuar como UM pedido — dizer isso no prompt com esse exemplo.
  - `adicionar(comando, prioridade=2, motor="claude") -> id`; `proxima() -> dict|None` (marca
    como `rodando` a pendente de menor prioridade e mais antiga, de forma atômica:
    `BEGIN IMMEDIATE`); `concluir(id, status, resposta="")`; `cancelar(id) -> bool` (só
    pendente ou rodando); `listar(ativas=True) -> list[dict]` (pendentes e rodando, ordenadas
    por prioridade e criação); `recuperar()` — na inicialização, tarefas que ficaram `rodando`
    (motor caiu) voltam para `pendente`.
- Testes: prioridade e limpeza do texto; ordem de `proxima` (urgente passa na frente, empate
  pela mais antiga); `cancelar`; `recuperar`; `dividir_pedidos` com `chamar` falso (dividido,
  não dividido, JSON inválido → `[texto]`) e sem conector não chama o modelo.

## T19 — Motor multitarefa (executor da fila)
- Depende de: T10, T14, T18. Arquivos: `voz/assistente_voz.py`.
- Fazer:
  - Pedido novo (voz ou texto) que não é comando de controle: `detectar_prioridade` →
    `dividir_pedidos` → `fila.adicionar` para cada parte. Fala curta: 1 tarefa → "Certo." se
    nada estiver rodando, senão "Anotei, está na fila." / com prioridade 0 → "Urgente, vou
    fazer agora."; várias → "Anotei N tarefas.". Emite `{"evento":"fila","tarefas":fila.listar()}`
    sempre que a fila muda.
  - Executor: uma thread despachante que, enquanto houver vaga, pega `fila.proxima()` e roda
    numa thread de trabalho. Vagas: 2 com motor Claude, 1 com Gemma. Remove o bloqueio atual
    "Ainda estou na tarefa anterior".
  - Sessões Claude: a primeira tarefa simultânea usa a sessão da conversa (`--resume`); se outra
    já estiver rodando, a nova usa `--resume <sessao> --fork-session` (ou sessão nova se ainda
    não houver nenhuma) e NÃO substitui `self.sessao` com o id derivado.
  - Estado por tarefa: guardar `{id: {"proc", "cancelado"}}` em vez de `self.proc`/`self.cancelado`
    únicos. "secretário, cancela" sem número cancela a mais recente rodando; `{"cmd":"cancelar",
    "id": N}` cancela uma específica; "cancela tudo" cancela todas (rodando e pendentes).
  - Toda mensagem/ferramenta emitida passa a levar `"tarefa": id`. Respostas faladas entram
    numa fila de fala (uma por vez), prefixadas com o resumo do pedido quando houver mais de
    uma tarefa rodando ("Sobre o e-mail: ...").
  - Ao iniciar: `fila.recuperar()` e retomar pendentes.
- Verificação: `py_compile`; testes existentes passam.

## T20 — Painel da fila na interface
- Depende de: T19. Arquivos: `app/renderer.js`, `app/index.html`, `app/estilo.css`, `app/preload.js` se precisar.
- Fazer: acima do compositor, uma faixa recolhível "Fila (N)" que lista as tarefas ativas do
  evento `fila`: ícone de estado (rodando = animado, pendente = relógio), etiqueta de prioridade
  (Urgente vermelho, Alta âmbar, Normal cinza, Baixa azul), texto do pedido cortado em uma
  linha e botão ✕ que envia `{cmd:"cancelar", id}`. Some quando a fila está vazia. O bloco
  "Trabalhando…" passa a mostrar quantas tarefas estão rodando. Passos/mensagens com `tarefa`
  continuam no chat normal.
- Verificação: `node --check app/renderer.js`.

## Ordem de execução da Fase 2
Paralelo: T8, T10, T11 → depois T9, T13, T18 (paralelo) → T12 → T14 → T15 → T19 → T20 → T16 → T17.
(Tarefas que alteram `voz/assistente_voz.py` rodam uma de cada vez.)

---

# Fase 3 — vários motores (Codex, Gemini, Grok, GPT…) e reconhecimento de voz melhor

Nota: a T15 (seletor Claude/Gemma) foi INCORPORADA à T23, que faz o seletor com todos os
motores do registro. Não execute a T15 separadamente. Onde outra tarefa diz "depende de
T15", leia "depende de T23" (exceto a T19, que não depende mais dela).

## T21 — Registro de provedores e chaves
- Arquivos: criar `voz/provedores.py` e `voz/tests/test_provedores.py`.
- Pode instalar: `keyring` no venv.
- Fazer:
  - `MOTORES`: dicionário com `nome → {"rotulo", "tipo", ...}`. Tipos:
    - `"cli"` (agentes que usam o computador sozinhos): `claude` (Claude Code), `codex`
      (`codex exec`), `gemini-cli` (`gemini -p`), `qwen` (`qwen -p`). Campo `executavel`.
    - `"api"` (formato OpenAI `/chat/completions`): `grok` (xAI, `https://api.x.ai/v1`,
      modelo padrão `grok-4`), `gpt` (`https://api.openai.com/v1`, `gpt-5`), `gemini`
      (`https://generativelanguage.googleapis.com/v1beta/openai`, `gemini-2.5-flash`),
      `deepseek` (`https://api.deepseek.com/v1`, `deepseek-chat`), `mistral`
      (`https://api.mistral.ai/v1`, `mistral-large-latest`), `openrouter`
      (`https://openrouter.ai/api/v1`, modelo configurável), `gemma` (Ollama em
      `http://localhost:11434/v1`, `gemma3:4b`, sem chave). Campos `url`, `modelo`, `chave`
      (nome da credencial; None para Ollama).
    - O modelo de cada motor pode ser sobrescrito em `voz/config.json` → `"modelos": {"grok": "..."}`.
  - Chaves: `salvar_chave(nome, valor)`, `ler_chave(nome)` com `keyring` (serviço
    `"secretario"`); se não houver no keyring, tenta a variável de ambiente
    (`XAI_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`,
    `OPENROUTER_API_KEY`). Nunca registrar chaves em log, evento ou exceção.
  - `disponivel(nome) -> (bool, motivo)`: cli → `shutil.which(executavel)`; api → tem chave
    (Ollama: responde em `/api/tags` com timeout 2 s).
  - `listar() -> list[dict]`: `{nome, rotulo, tipo, disponivel, motivo}` de todos.
  - `chamar_api(nome, mensagens, json=False, imagens=None, timeout=120) -> str`: POST em
    `<url>/chat/completions` com `Authorization: Bearer`, `temperature 0.2`; `json=True` →
    `response_format: {"type": "json_object"}`; imagens em base64 viram partes
    `{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}` na última
    mensagem do usuário. Erros HTTP viram `RuntimeError` com status e mensagem curta (sem a chave).
- Testes: `listar` com `shutil.which`/keyring falsos; `chamar_api` com `urlopen` falso
  verifica URL, cabeçalho, `response_format` e o formato das imagens; chave nunca aparece em
  mensagens de erro.

## T22 — Motores de linha de comando (Codex, Gemini CLI, Qwen)
- Depende de: T21. Arquivos: criar `voz/motores_cli.py` e `voz/tests/test_motores_cli.py`.
- Fazer: `montar_comando(nome, pedido, sessao=None, prompt_sistema="") -> list[str]` e
  `interpretar_linha(nome, linha) -> dict|None` (devolve `{"tipo": "sessao"|"ferramenta"|
  "resposta", ...}`), para:
  - `codex`: `codex exec --json -s workspace-write -C <home> "<prompt_sistema>\n\nPedido: <pedido>"`
    (retomar: `codex exec resume <sessao> ...` se `sessao`). Eventos JSONL: id da sessão/thread,
    itens de comando/ferramenta → ferramenta, última mensagem do agente → resposta.
  - `gemini-cli`: `gemini -p "<prompt>" --output-format json` (resposta no campo `response`).
  - `qwen`: `qwen -p "<prompt>" --output-format json` (mesmo formato do gemini-cli).
  Antes de fixar os formatos, rode `codex exec --help`, `gemini --help` (se instalado) e
  `qwen --help` e siga o que eles mostram; documente no topo do arquivo a versão observada.
  `executar(nome, pedido, ao_evento, sessao=None, prompt_sistema="") -> dict` roda o processo
  (stdin DEVNULL, sem janela), chama `ao_evento` para cada evento e devolve
  `{"resposta", "sessao", "ferramentas", "proc"}`; aceita ser cancelado matando a árvore
  (`taskkill /T /F`).
- Testes: `montar_comando` e `interpretar_linha` com linhas de exemplo de cada CLI.

## T23 — Motor configurável no assistente e na interface
- Depende de: T19, T21, T22. Arquivos: `voz/assistente_voz.py`, `app/main.js`,
  `app/renderer.js`, `app/index.html`, `app/estilo.css`.
- Fazer:
  - `self.motor` aceita qualquer nome de `provedores.MOTORES`. `claude` continua com o
    caminho atual; outros `cli` usam `motores_cli.executar` (mesmo prompt de voz e contexto de
    memória); `api` usam `agente_local.executar(..., chamar=<chamar_api do provedor>)` — assim
    Grok/GPT/Gemini/DeepSeek também usam o catálogo de ações (abrir, pesquisar, tela...).
  - Voz: "secretário, usar <motor>" reconhece claude/cloud, codex, gemini/gêmini/jemini (API
    se houver chave, senão gemini-cli), grok/groque, gpt/chat gpt, deepseek, mistral,
    openrouter, gemma. Motor indisponível → fala o motivo e não troca.
  - Evento `{"evento":"motores","lista":provedores.listar(),"atual":...}` ao iniciar e ao trocar;
    comando `{"cmd":"motor","valor":nome}`.
  - Interface: um menu suspenso no topo do chat, à esquerda da pílula de estado, com todos os motores
    (indisponíveis em cinza com o motivo no `title`), agrupados em "Agentes" e "Modelos (API)".
  - Bandeja: submenu "Motor" com itens `radio`.
  - Comando `{"cmd":"chave","motor":nome,"valor":"..."}` chama `provedores.salvar_chave` (para a
    tela de configurações da T27). A chave nunca volta para a interface.

## T24 — Reconhecimento de voz: vocabulário, correções, VAD e palavra de ativação
- Arquivos: `voz/comum.py`, `voz/assistente_voz.py`, criar `voz/vocabulario.py` e
  `voz/tests/test_vocabulario.py`.
- Fazer:
  - `vocabulario.termos(cofre=memoria.COFRE, limite=60) -> list[str]`: títulos e aliases do
    índice da memória (mais recentes primeiro) + nomes fixos (Deivid, Secretário, Claude,
    Gemma, Codex, Gemini, Grok, Obsidian).
  - `transcrever(audio)` usa `hotwords=" ".join(termos)` e `initial_prompt` curto com os 15
    primeiros termos; `vad_filter=True` com `vad_parameters={"min_silence_duration_ms": 500}`.
    Recarrega os termos no máximo a cada 5 minutos.
  - Correções: `vocabulario.corrigir(texto) -> str` aplica pares de `voz/correcoes.json`
    (`{"gloco de notas": "bloco de notas", "cloud": "Claude"}`) com fronteira de palavra,
    sem diferenciar maiúsculas; `aprender_correcao(errado, certo)` grava o par (normalizado,
    sem duplicar). `transcrever` aplica `corrigir` no fim.
  - Palavra de ativação tolerante: além da regex atual, aceitar a primeira ou segunda palavra
    com distância de edição ≤ 2 de "secretario" (`difflib.SequenceMatcher` ratio ≥ 0.8), ex.:
    "secretaria", "se cretário", "secretárie".
  - Modelo: `config.json` `"modelo_whisper"` aceita `small`, `medium`, `large-v3-turbo`.
- Testes: `corrigir` (fronteira de palavra, maiúsculas), `aprender_correcao`, ativação
  tolerante (aceita variações, rejeita "secretariado" e frases sem a palavra), `termos` com
  índice falso.

## T25 — Teste de velocidade do Whisper
- Arquivos: criar `voz/ferramentas/benchmark_whisper.py`.
- Fazer: gera 3 frases em português com a voz do Windows (pyttsx3 → wav em pasta temporária),
  e para cada modelo passado em `--modelos small,medium,large-v3-turbo` mede o tempo de carga e
  o tempo médio de transcrição (int8, CPU) e mostra a transcrição. Imprime uma tabela final.
  Não altera configuração nenhuma.
- Verificação: `py_compile`.

## T26 — Transcrição na nuvem opcional
- Depende de: T21, T24. Arquivos: `voz/comum.py`, `voz/provedores.py`.
- Fazer: `config.json` `"transcricao": "local" | "groq" | "openai"`. Nuvem: POST multipart em
  `https://api.groq.com/openai/v1/audio/transcriptions` (`whisper-large-v3-turbo`, chave
  `GROQ_API_KEY`/keyring "groq") ou `https://api.openai.com/v1/audio/transcriptions`
  (`gpt-4o-transcribe`), `language=pt`, `prompt` com os termos do vocabulário. Áudio float32 →
  WAV 16 kHz em memória (`wave` + `io`). Qualquer falha cai para o Whisper local na hora.
  Adicionar `groq` a `provedores` só como credencial (não é motor de chat).
- Verificação: `py_compile`; testes existentes passam.

## T27 — Configurações e correção de transcrição na interface
- Depende de: T23, T24, T26. Arquivos: `app/renderer.js`, `app/index.html`, `app/estilo.css`,
  `app/main.js`, `voz/assistente_voz.py`.
- Fazer:
  - Botão de engrenagem no painel do usuário abre um painel "Configurações": motor padrão,
    modelo do Whisper, transcrição local/nuvem, e um campo de chave para cada provedor de API
    (tipo password; mostra só "configurada"/"não configurada"; botão Salvar envia
    `{"cmd":"chave",...}`). Mudanças de config vão por `{"cmd":"config","chave":...,"valor":...}`
    e o motor grava em `voz/config.json`.
  - Em mensagens "por voz" do usuário, um ícone de lápis permite editar o texto; ao salvar,
    calcula as palavras que mudaram (difflib) e envia `{"cmd":"correcao","errado":...,"certo":...}`
    → `vocabulario.aprender_correcao`.
- Verificação: `node --check` nos .js; `py_compile`.

## Ordem de execução (Fase 3, depois da Fase 2)
Junto com a Fase 2: (T19 ‖ T21 ‖ T25) → (T20 ‖ T22 ‖ T24) → T26 → T23 → T16 → T17 → T27.
(Tarefas que alteram `voz/assistente_voz.py` rodam uma de cada vez.)

---

# Fase 4 — vários motores ao mesmo tempo e apresentação inicial

## T28 — Distribuir tarefas simultâneas entre motores
- Depende de: T19, T22, T23. Arquivos: `voz/assistente_voz.py`, `voz/config.py`,
  `voz/config.exemplo.json`, criar `voz/tests/test_distribuicao.py` (testar a função pura).
- Fazer:
  - Config `"motores_paralelos": ["claude", "codex", "gemma"]` (ordem de preferência) e
    `"vagas": {"claude": 2, "codex": 1, "gemini-cli": 1, "gemma": 1, "api": 2}` (`api` vale
    para cada motor do tipo api). O motor escolhido pelo usuário (`self.motor`) é sempre o
    primeiro da lista.
  - Função pura `escolher_motor(preferido, ocupacao, disponiveis, ordem, vagas) -> str|None`:
    devolve o preferido se tiver vaga; senão o primeiro da `ordem` que esteja disponível
    (`provedores.disponivel`) e com vaga; senão None (a tarefa espera na fila). Gemma nunca
    roda junto com outra tarefa Gemma (1 vaga, CPU).
  - O despachante usa `escolher_motor` para cada tarefa pendente (em ordem de prioridade) e
    grava na fila o motor efetivamente usado. A tarefa leva o contexto de memória (T16) e o
    prompt de voz qualquer que seja o motor.
  - Respostas continuam faladas uma de cada vez, na ordem em que terminam (fila de fala da
    T19); quando há mais de uma rodando, prefixo "Sobre <pedido>:" (já existe).
  - Evento `fila` passa a incluir o motor de cada tarefa; o painel da T20 mostra o nome do
    motor na linha da tarefa.
- Testes: preferido com vaga; preferido cheio → próximo disponível; indisponível é pulado;
  tudo cheio → None; segunda tarefa Gemma espera.

## T29 — Apresentação inicial (conhecer o usuário)
- Depende de: T9, T16. Arquivos: `app/renderer.js`, `app/index.html`, `app/estilo.css`,
  `voz/assistente_voz.py`, `voz/memoria.py`, criar `voz/tests/test_perfil_inicial.py`.
- Fazer:
  - Na primeira execução (sem `"perfil_inicial": true` em `voz/config.json`), a interface
    mostra um assistente de boas-vindas em etapas (uma pergunta por tela, com botões
    Voltar/Próximo/Pular e barra de progresso). Cada pergunta pode ser respondida digitando
    ou pelo botão de microfone (usa `{"cmd":"ditar"}` → o motor grava uma fala, transcreve e
    devolve `{"evento":"ditado","texto":...}` sem executar nada).
  - Perguntas: 1) como prefere ser chamado; 2) o que faz (profissão/ocupação); 3) onde
    mora (cidade); 4) rotina — horários em que mais precisa de ajuda; 5) tarefas
    repetitivas que mais quer delegar; 6) assuntos de interesse (múltipla escolha com os
    `memoria.ASSUNTOS` + campo livre); 7) estilo das respostas (curtas e diretas /
    detalhadas; formal / informal); 8) o que o secretário nunca deve fazer sem perguntar.
  - Ao concluir: `{"cmd":"perfil_inicial","respostas":{...}}` → `memoria.salvar_perfil_inicial(
    respostas, cofre)` grava `Perfil/Dados pessoais.md` (nome, cidade, ocupação — sem apagar
    campos existentes), `Preferências/Estilo.md` (novo: estilo, rotina, nunca fazer),
    `Perfil/Aprendizados.md` (tarefas a delegar) e cria as ligações com os hubs de assunto
    escolhidos (`Assuntos/<X>.md` ganha "- Interesse do Deivid"), depois `indexar`. Marca
    `"perfil_inicial": true` no config. Botão "Refazer apresentação" nas Configurações (T27).
  - `voz_prompt.md` e `PROMPT_LOCAL`: incluir uma linha dizendo para seguir
    `Preferências/Estilo.md` (o contexto de memória da T16 já traz o resumo).
- Testes: `salvar_perfil_inicial` em cofre temporário cria/atualiza as notas sem apagar
  dados existentes e liga os assuntos escolhidos.

## Ordem de execução atualizada
(T20 ‖ T24) → T26 → T23 → T28 → T16 → T17 → T29 → T27.

---

# Fase 5 — delegar trabalho a outros agentes e entender melhor a fala do Deivid

## T30 — Delegar tarefas a agentes de linha de comando (Claude, Codex, Gemini, Qwen…)
- Arquivos: `voz/motores_cli.py` (acrescentar `claude`), criar `voz/delegacao.py` e
  `voz/tests/test_delegacao.py`; `voz/sentidos_mcp.py` (ferramentas novas); `voz/voz_prompt.md`;
  `C:\Users\deivi\.claude\skills\secretario\SKILL.md` NÃO (o revisor atualiza).
- Fazer:
  - `motores_cli`: motor `claude` → `claude -p <prompt> --output-format json --permission-mode auto`
    (resposta em `result`, sessão em `session_id`), resolvido com `resolver_executavel`.
  - `delegacao.py`: execução em segundo plano de um agente sobre uma tarefa de trabalho.
    `iniciar(agente, tarefa, pasta=None) -> id` (thread; pasta padrão = home; para `codex`
    passar `-C pasta`; para os outros, `cwd=pasta`), `estado(id) -> {id, agente, status
    (rodando|ok|erro|cancelada), inicio, fim, resposta (cortada em 4000), ferramentas}`,
    `cancelar(id)`, `listar()`. Guarda os trabalhos em memória e também em SQLite
    (`registro.BANCO`, tabela `delegacoes`). Proteção contra recursão: o processo filho
    recebe `SECRETARIO_DELEGACAO=1`; se essa variável já existir, `iniciar` recusa
    ("delegação aninhada não permitida"). Máximo de 3 delegações rodando ao mesmo tempo.
  - `sentidos_mcp.py`: ferramentas `delegar(agente, tarefa, pasta="")` → id e texto curto;
    `resultado_delegacao(id)`; `cancelar_delegacao(id)`; `agentes_disponiveis()` (de
    `provedores.listar()`, só tipo cli).
  - `voz_prompt.md`: seção curta "Delegar trabalho": use `delegar` para tarefas de trabalho
    longas e bem definidas que outro agente executa melhor ou em paralelo (ex.: código →
    `codex`; pesquisa ampla → `gemini-cli`); escreva a tarefa completa e autocontida (objetivo,
    arquivos/pasta, critério de pronto); acompanhe com `resultado_delegacao`; revise o
    resultado antes de dizer ao Deivid que está pronto.
- Testes: `iniciar` com executor falso (monkeypatch em `motores_cli.executar`), estados,
  cancelamento, limite de 3, recusa de recursão; `montar_comando("claude", ...)`.

## T31 — Padrão de fala: confiança por palavra, aprendizado de pronúncia, pausa adaptativa e idiomas
- Depende de: T24. Arquivos: `voz/comum.py`, `voz/vocabulario.py`, `voz/assistente_voz.py`,
  `voz/sentidos_mcp.py`, `voz/config.py`, `voz/voz_prompt.md`, criar `voz/padrao_fala.py`
  e `voz/tests/test_padrao_fala.py`.
- Fazer:
  - `transcrever(audio, detalhado=False)`: com `detalhado=True` usa `word_timestamps=True` e
    devolve `{"texto", "palavras": [{"palavra", "prob"}], "idioma", "prob_idioma"}`. O motor
    emite `{"evento":"transcricao","texto":...,"duvidosas":[palavras com prob < 0.5]}` junto
    com a mensagem do usuário (para a T32/T27 sublinhar na interface).
  - Aprendizado pela IA: ferramenta MCP `aprender_pronuncia(ouvido, correto)` →
    `vocabulario.aprender_correcao`, só aceita se `ouvido` tiver 2+ palavras OU for uma palavra
    que não está num dicionário básico de português (lista em `padrao_fala.PALAVRAS_COMUNS`,
    ~300 palavras frequentes) — evita trocar palavras comuns como "link" ou "gemas" sozinhas.
    `voz_prompt.md`: "o pedido vem de transcrição; quando você perceber que uma palavra foi
    transcrita errado e tiver certeza do que ele quis dizer (ex.: 'abre meu linketim' =
    LinkedIn), chame `aprender_pronuncia` com o trecho ouvido e o correto".
  - `padrao_fala.py`: `registrar_fala(texto, palavras, pausas)` acumula em SQLite (tabela
    `falas`: ts, texto, duvidosas, pausa_max_interna); `resumo() -> dict` (palavras mais
    usadas que não são comuns, correções mais aplicadas, pausa típica p90);
    `atualizar_nota(cofre)` grava `Perfil/Fala.md` (palavras e expressões dele, termos que o
    reconhecimento erra, pausa típica) — chamado uma vez por dia ou a cada 50 falas.
    `vocabulario.termos` inclui as 20 palavras mais usadas do `resumo`.
  - Pausa adaptativa: `Microfone.gravar_fala` mede as pausas internas (silêncios entre
    trechos de voz dentro da mesma fala) e devolve-as; a cada 30 falas, se `"pausa_auto": true`
    (padrão), ajusta `pausa_fala = clamp(p90 + 0.3, 1.0, 2.2)` no config.
  - Idiomas: config `"idiomas": ["pt"]` (padrão) ou ex.: `["pt", "en"]`. Se a transcrição em
    pt vier com `prob_idioma < 0.5` e houver outro idioma configurado, transcreve de novo com
    detecção automática e usa o resultado se a probabilidade for maior. A interface de
    configurações (T27) lista os idiomas; para a voz de resposta, avisar se não houver voz
    do Windows para o idioma (Configurações > Hora e idioma > Fala).
- Testes: filtro do `aprender_pronuncia`; `resumo` e `atualizar_nota` em banco/cofre
  temporários; cálculo da pausa adaptativa com limites; escolha de idioma com função de
  transcrição falsa.

## T32 — Calibração por palavras-chave
- Depende de: T31 (e do comando `ditar` da T29; se ainda não existir, crie-o aqui:
  `{"cmd":"ditar"}` → grava uma fala, transcreve e devolve `{"evento":"ditado","texto",
  "palavras"}` sem executar nada). Arquivos: `app/renderer.js`, `app/index.html`,
  `app/estilo.css`, `voz/assistente_voz.py`, `voz/padrao_fala.py`.
- Fazer: tela "Calibrar voz" (botão no cartão de voz e nas Configurações):
  1) Ruído: pede 3 s de silêncio e recalibra o limiar do microfone (`Microfone._calibrar`).
  2) Palavras-chave: mostra uma por vez (FIXOS do vocabulário + 10 termos do cofre + termos
     que o Deivid acrescentar num campo "adicionar palavra"), ele fala, o app mostra o que foi
     entendido com ✓ ou ✗. Para cada ✗, cria a correção `ouvido → esperado` (com
     `vocabulario.aprender_correcao`, respeitando o mesmo filtro da T31) e pede para repetir
     uma vez para confirmar.
  3) Frase longa com pausas: pede para ler uma frase com uma pausa no meio e ajusta
     `pausa_fala` com a pausa medida.
  Ao final, resumo: quantas palavras certas, correções criadas, nova pausa. Grava em
  `Perfil/Fala.md` a data da última calibração.
- Verificação: `node --check`; `py_compile`; testes existentes passam.

## Ordem de execução atualizada
(T26 ‖ T30) → T23 → T28 → T16 → T17 → T31 → T29 → T32 → T27.

---

# Fase 6 — vozes baixáveis

## T33 — Vozes de resposta além da voz do Windows (Piper local e Edge online)
- Depende de: T23 (mexe nos mesmos arquivos da interface). Arquivos: criar `voz/vozes.py`,
  `voz/falar_proc.py` e `voz/tests/test_vozes.py`; `voz/comum.py` (`falar`), `voz/config.py`,
  `voz/assistente_voz.py`, `voz/sentidos_mcp.py`, `voz/voz_prompt.md`, `app/main.js`,
  `app/renderer.js`, `app/index.html`, `app/estilo.css`, `voz/requirements.txt` (se existir).
- Pacotes (o revisor instala antes; leia o código deles em `voz/.venv/Lib/site-packages` para
  usar a API da versão instalada): `piper-tts`, `edge-tts`, `miniaudio`.
- Fazer:
  - `vozes.py` — catálogo `CATALOGO` com id, nome, tipo, idioma, tamanho aproximado, online:
    - `windows` (padrão): voz SAPI instalada (pyttsx3), como hoje.
    - Piper (local, neural, offline), baixadas de
      `https://huggingface.co/rhasspy/piper-voices/resolve/main/<lang>/<locale>/<nome>/<qual>/<locale>-<nome>-<qual>.onnx`
      e `.onnx.json`: `piper:pt_BR-faber-medium`, `piper:pt_BR-cadu-medium`,
      `piper:pt_BR-jeff-medium`, `piper:pt_BR-edresson-low`, `piper:pt_PT-tugão-medium`
      (codifique o "ã" na URL), `piper:en_US-amy-medium`.
    - Edge (online, gratuita, o texto vai para a Microsoft): `edge:pt-BR-FranciscaNeural`,
      `edge:pt-BR-AntonioNeural`, `edge:pt-BR-ThalitaMultilingualNeural`.
  - Funções: `pasta_modelos()` = `voz/modelos_voz/` (no .gitignore); `listar()` → lista de dicts
    com `instalada` (Piper: os dois arquivos existem; windows/edge: sempre True);
    `baixar(id, progresso=None)` baixa com urllib para `.part`, chama `progresso(feito, total)`,
    confere que o `.onnx.json` é JSON válido e só então renomeia; aceita só ids do catálogo
    (nada de URL livre); `remover(id)`; `sintetizar(texto, id, velocidade)` →
    `(amostras_float32, taxa)`; Piper: `length_scale = 190 / velocidade`; Edge: `rate`
    `"+N%"`/`"-N%"` a partir de `velocidade/190`, áudio mp3 decodificado com `miniaudio`.
  - `falar_proc.py`: processo de fala que **fica aberto** (testado aqui: Piper 1.8 levou ~8 s
    para 2,7 s de áudio contando o carregamento do modelo de 63 MB; Edge ~1,5 s). Lê linhas
    JSON no stdin `{"texto","voz","velocidade"}`, guarda a `PiperVoice` carregada entre falas,
    sintetiza frase por frase (`voice.synthesize(texto, syn_config=SynthesisConfig(
    length_scale=...))` devolve pedaços com `audio_float_array` e `config.sample_rate`) e toca
    cada pedaço com `sounddevice` assim que fica pronto; ao terminar escreve `{"fim":true}` no
    stdout. Windows continua com pyttsx3. Se a voz escolhida falhar (não instalada, sem
    internet, erro do pacote), escreve o erro no stderr e fala com a voz do Windows — nunca
    fica mudo. `comum.falar(texto, esperar)` usa um único processo global (recria se morreu);
    interromper a fala continua sendo matar o processo (o próximo `falar` recria). Mantenha
    um objeto com `.kill()`, `.wait()` e `.poll()` como retorno, para o código que hoje
    interrompe com `proc.kill()` continuar funcionando.
  - `config.py`: `"voz": "windows"`.
  - Motor (`assistente_voz.py`): comandos IPC `{"cmd":"vozes"}` → evento
    `{"evento":"vozes","lista":[...],"atual":id}`; `{"cmd":"voz","valor":id}` grava no config e
    responde com `vozes`; `{"cmd":"baixar_voz","valor":id}` baixa em thread, emite
    `{"evento":"download_voz","id","feito","total"}` (no máximo 1 evento por 5%) e no fim `vozes`
    ou `erro`; `{"cmd":"amostra_voz","valor":id}` fala "Olá, Deivid. Esta é a minha nova voz."
  - Voz por comando falado (regex no `executar`, antes da fila): "usa a voz <nome>" / "troca a
    voz para <nome>" → procura pelo nome curto (faber, cadu, jeff, edresson, francisca, antonio,
    thalita, windows/maria); se não estiver instalada, responde "Essa voz ainda não foi baixada,
    quer que eu baixe?" e um "sim" na próxima fala baixa e ativa.
  - `sentidos_mcp.py`: `vozes_disponiveis()`, `baixar_voz(id)`, `usar_voz(id)`.
  - Interface: no cartão de voz, botão "Voz" abre um painel com a lista (nome, local/online,
    tamanho, estado), botões "Baixar" (barra de progresso), "Ouvir", "Usar" e "Remover"; a
    voz atual marcada. Vozes online mostram o aviso "usa internet; o texto é enviado à
    Microsoft".
- Testes (sem rede e sem áudio): catálogo e URLs; `baixar` com `urllib.request.urlopen` falso
  (progresso, `.part`, JSON inválido rejeitado, id fora do catálogo recusado); `listar` com pasta
  temporária; conversão de velocidade para Piper e Edge; queda para a voz do Windows quando
  `sintetizar` levanta erro; regex do comando falado.
- Verificação: `node --check` nos .js; não rode o Python do venv (o revisor roda).

---

# Fase 7 — conviver com o Deivid usando o computador

## T34 — Microfone compartilhado: não prender o dispositivo
- Arquivos: `voz/comum.py` (`Microfone`), criar `voz/dispositivos.py` e
  `voz/tests/test_dispositivos.py`; `voz/assistente_voz.py`, `voz/config.py`, `app/main.js`,
  `app/renderer.js`, `app/index.html`, `app/estilo.css`.
- Fazer:
  - `Microfone.liberar()` fecha o stream (o ícone de microfone do Windows apaga) e
    `Microfone.retomar()` reabre e recalibra. Mutar pelo usuário (`pausado`) passa a liberar de
    verdade, não só descartar o áudio. Abrir sempre em modo compartilhado (nunca exclusivo;
    se o dispositivo for WASAPI, `sd.WasapiSettings(exclusive=False)`).
  - Recuperação: se o stream der erro ou o dispositivo sumir (fone desconectado), tenta reabrir
    com o dispositivo padrão a cada 2 s, sem derrubar o motor; emite `estado` com o aviso.
  - `dispositivos.apps_usando_microfone()` lê no registro
    `HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone`
    (subchaves de apps e `NonPackaged\<caminho com #>`): em uso = `LastUsedTimeStart > 0` e
    `LastUsedTimeStop == 0`. Ignora o próprio secretário: testado aqui, o Windows registra o
    motor como o Python BASE (`C:#Users#deivi#AppData#Local#Programs#Python#Python312#python.exe`),
    não o do venv — compare com `sys._base_executable` (trocando `\` por `#`, sem diferenciar
    maiúsculas) e ignore também caminhos com `electron.exe` do app. Devolve nomes amigáveis (Discord.exe → "Discord", chrome.exe → "Chrome", etc.).
  - Config `"mic_em_chamada": "liberar"` (padrão) | `"compartilhar"`: com "liberar", o motor
    consulta a cada 3 s; se outro app está usando o microfone, chama `liberar()` e emite
    `{"evento":"microfone","estado":"liberado","app":"Discord"}`; quando o outro app soltar,
    `retomar()`. Durante a chamada, as respostas não são faladas (só aparecem no app e numa
    notificação do Windows), para não vazar som na ligação. O atalho Ctrl+Shift+Space continua
    funcionando: abre o microfone só para aquele comando (aperte para falar) e libera depois.
  - Config `"modo_microfone": "continuo"` (padrão) | `"sob_demanda"`: sob demanda, o microfone
    só abre pelo atalho/botão e fecha ao fim da janela de conversa (`janela_conversa`).
  - Interface: no cartão de voz, o estado "Microfone liberado — Discord em uso" e a escolha
    contínuo/sob demanda.
- Testes: `apps_usando_microfone` com `winreg` falso (em uso, parado, o próprio secretário
  ignorado, NonPackaged com #); máquina de estados liberar/retomar com stream falso; recuperação
  após erro do stream.

## T35 — Trabalhar por trás sem atrapalhar o Deivid
- Arquivos: criar `voz/segundo_plano.py` e `voz/tests/test_segundo_plano.py`;
  `voz/sentidos_mcp.py`, `voz/acoes.py`, `voz/voz_prompt.md`. Pacote `pywinauto` (o revisor
  instala; leia o código dele no venv).
- Fazer:
  - `segundo_plano.ocioso_ha()` → segundos desde a última tecla/mouse do usuário
    (`GetLastInputInfo`). `esperar_vez(min_ocioso=2.0, max_espera=120)`: ações que usam o mouse
    ou teclado de verdade esperam ele parar de mexer; devolve False se ele não parou.
  - `restaurando_estado()` (context manager): guarda janela em primeiro plano, posição do
    cursor e conteúdo da área de transferência; depois da ação, devolve tudo como estava.
  - Ferramentas que NÃO usam o mouse/teclado nem trocam o foco (UI Automation via pywinauto
    backend "uia"; captura via `PrintWindow` com `PW_RENDERFULLCONTENT`):
    - `capturar_janela(titulo)` → imagem só daquela janela, mesmo atrás de outras
      (minimizada: avisa que precisa estar restaurada).
    - `ler_janela(titulo, limite=4000)` → lista compacta de elementos com índice, tipo, nome,
      valor e automation_id (como o snapshot do Playwright).
    - `preencher_campo(titulo, alvo, texto)` → `ValuePattern.SetValue` (alvo = índice, nome ou
      automation_id).
    - `acionar(titulo, alvo)` → Invoke, Toggle ou SelectionItem, o que o elemento suportar.
    Se o app não expõe UI Automation, a ferramenta diz isso (aí o agente usa as físicas).
  - Ferramentas físicas existentes (`clicar`, `arrastar`, `digitar`, `teclas`, `rolar`,
    `focar_janela`): passam por `esperar_vez` + `restaurando_estado`. Se ele não parar de
    mexer em 2 min, devolvem "O Deivid está usando o computador; não interrompi." `digitar`
    não pode mais perder o que ele tinha copiado.
  - `acoes.py` (Gemma): as mesmas regras nas ações físicas.
  - `voz_prompt.md` e o skill (o revisor atualiza o skill): seção "Trabalhar sem atrapalhar":
    ordem de preferência — sites: Playwright (não usa o mouse/teclado dele); programas:
    `ler_janela`/`preencher_campo`/`acionar`/`capturar_janela`; mouse e teclado de verdade só
    em último caso. Nunca trazer uma janela para frente, fechar, mover ou minimizar janelas dele
    enquanto ele trabalha, a menos que ele peça.
- Testes: `esperar_vez` com relógio e `ocioso_ha` falsos; `restaurando_estado` com funções
  win32 falsas (restaura mesmo se a ação levantar erro); resolução do `alvo` (índice, nome,
  automation_id) com árvore falsa; ferramentas físicas recusam quando ele não para.

---

# Fase 8 — cuidar de si mesmo: backup, auto-reparo e instalação

## T37 — Backup sólido do SQLite e dos dados do secretário
- Arquivos: criar `voz/backup.py` e `voz/tests/test_backup.py`; `voz/config.py`,
  `voz/assistente_voz.py`, `voz/sentidos_mcp.py`, `voz/registro.py`.
- Fazer:
  - `fazer_backup(motivo)`: cria `<pasta_backup>/AAAA-MM-DD_HHMMSS_<motivo>/` com
    `secretario.db` copiado pela API `sqlite3.Connection.backup()` (cópia consistente com WAL e
    com o motor rodando — nunca copiar o arquivo direto), `config.json`, `correcoes.json`,
    `lembretes.json`, `motor.txt` (os que existirem) e `cofre.zip` do cofre do Obsidian (sem
    `.obsidian/workspace*`). Roda `PRAGMA integrity_check` na cópia e grava `manifesto.json`
    (sha256 e tamanho de cada arquivo, linhas por tabela, resultado da verificação). Se a
    verificação falhar, apaga a pasta e levanta erro.
  - Config `"pasta_backup"` (padrão `%USERPROFILE%\Backups\Secretario`) e
    `"pasta_backup_extra"` (opcional, ex.: uma pasta do OneDrive, para ter cópia fora do PC):
    o backup é copiado para as duas.
  - Rotação: mantém 7 diários, 4 semanais e 6 mensais; backups com motivo `antes_reparo` ou
    `antes_restaurar` ficam 30 dias.
  - Quando: ao iniciar o motor, se o último backup tem mais de 24 h; antes de cada auto-reparo
    (T36); antes de restaurar; e por pedido.
  - `verificar_banco()` ao iniciar: `PRAGMA integrity_check` no banco ativo; se falhar, avisa
    o Deivid e oferece restaurar o último backup íntegro.
  - `listar_backups()`, `restaurar(nome)`: faz `fazer_backup("antes_restaurar")`, para as
    escritas (o motor chama com a fila pausada), substitui o banco e os arquivos, e pede
    reinício. Restaurar sempre exige confirmação do Deivid.
  - As chaves de API ficam no Gerenciador de Credenciais do Windows e NÃO entram no backup
    (o manifesto registra isso).
  - Voz: "faz um backup" (regex no `executar`); MCP `fazer_backup`, `listar_backups`,
    `restaurar_backup` (a ferramenta só restaura com `confirmado=true`).
- Testes: backup de um banco temporário em WAL com escrita concorrente; manifesto; integridade
  falha → pasta removida; rotação com datas falsas; restauração faz backup antes.

## T36 — Auto-diagnóstico, relato de bugs e auto-reparo com aprovação
- Depende de: T37. Arquivos: criar `voz/diagnostico.py`, `voz/reparo.py` e testes;
  `voz/registro.py`, `voz/assistente_voz.py`, `voz/sentidos_mcp.py`, `voz/voz_prompt.md`,
  `app/main.js`, `app/renderer.js`, `app/index.html`, `app/estilo.css`.
- Captura de bugs (`diagnostico.py`):
  - `sys.excepthook`, `threading.excepthook` e os `except` genéricos do motor chamam
    `registrar_bug(origem, erro, traceback, contexto)`. Tabela `bugs` no SQLite: id,
    assinatura (hash do tipo do erro + arquivo/função do último quadro do nosso código, sem
    números de linha), tipo (bug|melhoria), resumo, traceback, contexto (pedido, motor,
    ferramenta — sem chaves nem textos longos), primeira_vez, ultima_vez, ocorrencias, estado
    (novo|informado|aprovado|corrigindo|corrigido|falhou|ignorado), diretriz, commit.
  - O app (`main.js`) registra quedas do motor (código de saída, últimas 50 linhas do stderr)
    em `voz/sinais/bug_<ts>.json`; o motor importa esses arquivos ao iniciar.
  - Sintomas sem exceção, a partir da tabela `eventos`: o mesmo erro de motor 3 vezes em 1 h,
    5 transcrições vazias seguidas, ferramenta falhando 3 vezes seguidas.
  - `verificar_saude(completo=False)`: banco íntegro, cofre existe, Ollama responde, microfone
    abre, espaço em disco > 2 GB; com `completo=True` também roda `pytest voz/tests -q`
    (timeout 5 min). Leve ao iniciar; completo uma vez por dia quando ele estiver ocioso.
- Informar e pedir diretriz:
  - Bug novo (ou que passou de 3 ocorrências) → fala em uma frase, quando ele não estiver em
    chamada nem no meio de uma tarefa: "Encontrei um problema: <resumo>. Quer que eu tente
    corrigir? Se tiver alguma orientação, pode falar." Estado → informado. Não repetir o
    mesmo aviso no mesmo dia.
  - Painel "Problemas" na interface (ícone na barra lateral com contador): lista, detalhes
    (resumo, quando, quantas vezes, traceback recolhido), campo "Orientação" e botões
    "Corrigir", "Ignorar". Voz: "o que deu errado?", "corrige o problema", "anota uma
    melhoria: …" (vira registro tipo melhoria). MCP `listar_bugs`, `detalhe_bug`,
    `corrigir_bug(id, diretriz)` (só depois da aprovação dele na conversa).
- Auto-reparo (`reparo.py`), só com aprovação explícita para aquele bug:
  1. Recusa se o repositório tiver alterações não commitadas ou outro reparo rodando.
  2. `backup.fazer_backup("antes_reparo")`; cria branch `reparo/<id>`.
  3. Delega ao Codex (`motores_cli.executar("codex", …, pasta=repo)`) com: resumo, traceback,
     contexto, a diretriz do Deivid e as regras — corrigir só esse problema, acrescentar um
     teste que reproduz o bug, não mexer em dados do usuário (`secretario.db`, `config.json`,
     `correcoes.json`, cofre, chaves), não fazer commit.
  4. Roda `pytest voz/tests -q` e `node --check` nos .js. Passou → commit no branch, merge na
     main (`--ff-only`), estado corrigido, grava o commit; diz "Corrigi <resumo>. Posso me
     reiniciar para aplicar?". Falhou → volta para a main, apaga o branch, estado falhou (até
     2 tentativas por bug) e conta o motivo em uma frase.
  5. Proteção: o app marca a tag git `estavel` depois de 30 min do motor rodando sem queda. Se,
     após um reparo, o motor cair 2 vezes em 5 min, o app faz `git revert` do commit do reparo,
     reinicia e avisa o Deivid. Nunca `git push`.
- Testes: assinatura estável (mesmo bug em linhas diferentes = mesma assinatura); contagem
  e estados; sintomas a partir de eventos falsos; reparo com git em pasta temporária e executor
  falso (sucesso → commit na main; testes falham → main intacta e branch apagado; repositório
  sujo → recusa).

## T38 — Instalação: baixar, instalar e configurar tudo sozinho
- Depende de: todas as anteriores (instala o que existir). Arquivos: criar
  `instalacao/instalar.ps1`, `instalacao/skill/SKILL.md` e `instalacao/agente/secretario.md`
  (cópias versionadas; o revisor copia as atuais), `instalacao/cofre_modelo/` (esqueleto do
  cofre sem dados pessoais), `voz/requirements.txt` (o revisor gera com versões fixas);
  `voz/diagnostico.py` (modo `--instalacao`), `app/main.js`, `app/renderer.js`.
- Também: procurar caminhos fixos com `deivi` no código e trocar por `Path.home()`,
  `os.environ` ou caminhos relativos ao repositório (o nome "Deivid" nos textos pode ficar até
  a T29 trocar pelo nome do perfil).
- `instalar.ps1` (PowerShell 5.1, idempotente: cada passo verifica antes e só instala o que
  falta; log em `instalacao\instalar.log`; tabela final ok/instalado/falhou/ação do usuário):
  1. winget disponível. 2. Python 3.12, Node LTS, Git, Ollama e Obsidian via winget (ids
     `Python.Python.3.12`, `OpenJS.NodeJS.LTS`, `Git.Git`, `Ollama.Ollama`,
     `Obsidian.Obsidian`), atualizando o PATH da sessão depois.
  3. venv em `voz\.venv` e `pip install -r requirements.txt` (se o ensurepip estiver quebrado,
     usar a roda do pip que vem no Python: `Lib\ensurepip\_bundled\pip-*.whl`).
  4. `npm ci` em `app\`. 5. `npm install -g @anthropic-ai/claude-code @openai/codex`.
  6. MCPs no escopo do usuário: `claude mcp add -s user playwright -- npx @playwright/mcp@latest`
     e `sentidos` apontando para o Python do venv e `voz\sentidos_mcp.py` (remove e adiciona
     se o caminho mudou); `npx playwright install chromium`.
  7. Copia skill e agente para `~\.claude\skills\secretario\` e `~\.claude\agents\` (se já
     existe e é diferente, guarda a antiga como `.bak`).
  8. Cofre: cria `Documents\Secretario` do modelo se não existir; registra no `obsidian.json`
     somando ao que já existe (nunca substituir os cofres dele).
  9. Modelos: `ollama pull gemma3:4b`, baixa o Whisper `small` (chamando o Python do venv) e,
     com `-Voz faber`, a voz Piper. Flag `-SemModelos` pula este passo.
  10. `config.json` a partir do `config.exemplo.json` se não existir.
  11. Atalho na área de trabalho e iniciar com o Windows.
  12. `python voz\diagnostico.py --instalacao` → verificação final.
  - Logins e chaves NUNCA são automatizados: no fim, lista o que ele precisa fazer (`claude`
    para entrar, `codex login`, chaves de API pela tela de Configurações).
  - `-Verificar`: só confere e mostra a tabela, sem instalar nada.
- App: botão "Verificar instalação" (e verificação ao iniciar) usa `diagnostico.py
  --instalacao`; se faltar algo, avisa e oferece rodar o passo do `instalar.ps1` — instalar
  programa sempre pede confirmação.
- Verificação: o revisor roda `instalar.ps1 -Verificar` de verdade e checa o parse com
  `[System.Management.Automation.Language.Parser]::ParseFile`.

---

# Fase 9 — Secretário no celular (Android, cérebro híbrido)

Decisões do Deivid (27/10/2026): Android; cérebro híbrido (usa o secretário do PC quando
alcançável, senão uma IA na nuvem com chave dele); gastos por voz/texto, foto de comprovante,
leitura de notificações de compra e importação de CSV. Executa ações em apps, **nunca em apps
de banco/finanças**. Cresce com o uso.

Regras da fase: projeto em `celular/` (Kotlin, Jetpack Compose, minSdk 29, targetSdk 35,
pacote `com.deivid.secretario`); APK instalado por fora da Play Store (uso pessoal). O revisor
compila (`gradlew assembleDebug`) — o Codex não roda Gradle. Pré-requisitos no PC (o revisor
instala com a confirmação do Deivid): JDK 17 e Android SDK command-line tools; Tailscale no PC e
no celular para acesso fora de casa.

## C1 — Ponte PC ↔ celular
- Arquivos: criar `voz/ponte.py`, `voz/tests/test_ponte.py`; `voz/assistente_voz.py`,
  `app/main.js`, `app/renderer.js`, `app/index.html`.
- Servidor HTTP + WebSocket (pacote `websockets` ou `aiohttp`) dentro do motor, porta 8765,
  escutando SÓ no IP do Tailscale (100.x) e no IP da rede local — nunca 0.0.0.0 em rede pública.
- Pareamento: botão "Conectar celular" no app mostra um QR com `{host_lan, host_tailscale,
  porta, token}`; token aleatório de 32 bytes por aparelho, guardado com hash no SQLite
  (`aparelhos`: id, nome, hash, criado, ultimo_uso, revogado). Lista de aparelhos com "Revogar".
- Endpoints (todos exigem `Authorization: Bearer`): WS `/eventos` (mesmos eventos do IPC:
  mensagem, estado, fila, motores); `POST /comando` (texto, com `origem:"celular"`);
  `POST /gastos` e `GET /gastos?desde=` (C5); `POST /memoria/fatos` (fatos aprendidos no
  celular → `memoria.aprender`); `GET /memoria/contexto?q=` (`memoria.contexto`);
  `POST /bugs` (T36); `GET /apk` (C9).
- Pedidos vindos do celular entram na mesma fila (T18), com a resposta devolvida pelo WS
  (e não falada no PC, a menos que ele esteja em casa e peça).
- Limite de 60 requisições/min por aparelho; tudo registrado em `eventos`.
- Testes: token válido/inválido/revogado, limite de taxa, endereço de escuta nunca 0.0.0.0.

## C2 — App Android base: conversa, voz e roteador do cérebro
- Arquivos: `celular/` (projeto Gradle completo com wrapper), README com como compilar.
- Telas no estilo do app do PC (escuro, menta): conversa, botão de microfone, painel da fila,
  Configurações (PC pareado via leitura do QR com CameraX/ML Kit; chave da IA na nuvem guardada
  com EncryptedSharedPreferences/Android Keystore; motor da nuvem: Gemini, GPT, Grok,
  OpenRouter — API compatível com OpenAI).
- Voz: `SpeechRecognizer` pt-BR (offline quando disponível) e `TextToSpeech` do Android.
  Acesso rápido: bloco nas Configurações rápidas, widget e atalho do app.
- Roteador: se o PC responde em até 1,5 s → manda para o PC (C1); senão → IA na nuvem com o
  catálogo de ações do celular (C3/C4) por chamada de função. Indicador "PC" / "Nuvem" na tela.
- Histórico local em Room; fatos aprendidos ficam numa fila e sobem ao PC quando ele aparecer.

## C3 — Ações por intents (sem Acessibilidade)
- Abrir app; agenda: ler eventos (`CalendarContract`, inclui Google Agenda) — "o que tenho
  amanhã?" — e criar evento (confirmação); alarme/timer; abrir mapa/rota; rascunho de
  SMS/WhatsApp/e-mail (ele envia); compartilhar texto+imagem para um app (base das postagens).
- Lembretes do celular sincronizados com os do PC (T5) pela ponte.

## C4 — Operar apps com Acessibilidade (exceto banco)
- `AccessibilityService`: lê a árvore da tela do app em primeiro plano (texto, ids, clicável,
  editável) em formato compacto com índices; ações: tocar, preencher texto (`ACTION_SET_TEXT`),
  rolar, voltar, gesto. Loop de ações com a IA (como o `agente_local` do PC), máx. 15 passos.
- **Bloqueio de apps financeiros** (antes de qualquer leitura ou ação, e os eventos desses
  apps são descartados sem ler): lista fixa de pacotes (Itaú, Bradesco, BB, Caixa, Santander,
  Nubank, Inter, C6, PicPay, Mercado Pago, PagBank, Neon, Next, Original, BTG, XP, Rico,
  Sicoob, Sicredi, Banrisul, Binance, carteiras de cripto…), mais heurística no nome do pacote
  (bank, banco, pay, wallet, invest, cartao, credito, cripto) e janelas com `FLAG_SECURE`.
  O Deivid pode acrescentar apps à lista, nunca remover os fixos.
- Nunca lê nem preenche campos de senha (`isPassword`); não faz login, CAPTCHA nem códigos.
- Confirmação antes de publicar, enviar mensagem, comprar, apagar ou aceitar termos.
- Não atrapalhar: se ele tocar na tela, a automação pausa; botão flutuante "Parar".
- README: no Android 13+, apps instalados por fora da loja precisam de "Permitir
  configurações restritas" (Informações do app) antes de ligar a Acessibilidade.

## C5 — Gastos
- Room `gastos` (id, data, valor_centavos, descricao, estabelecimento, categoria, forma,
  origem: voz|foto|notificacao|csv, confirmado), sincronizado com a tabela `gastos` do PC (C1)
  e incluído no backup (T37).
- Voz/texto: "gastei 45 reais no mercado ontem" → extração por regex para valor/data e IA para
  categoria; mostra e confirma.
- Foto: CameraX → texto com ML Kit no aparelho → IA extrai valor, data, estabelecimento.
- Notificações (opcional, desligado por padrão): `NotificationListenerService` lê só
  notificações de compra (valor em R$ + palavras como compra/aprovada/pix enviado) dos apps
  que ele marcar; guarda só os campos extraídos, nunca o texto completo; nunca abre o app.
- CSV: importação com mapeamento de colunas e detecção de duplicados.
- Categorias aprendidas pelas correções dele; orçamento por categoria com aviso aos 80%;
  "quanto gastei esse mês com mercado?"; o PC gera `Finanças/Gastos AAAA-MM.md` no cofre
  (resumo, sem dados de cartão). Nunca paga nada, nem Pix, nem boleto.

## C6 — Postagens
- "Cria uma postagem sobre X para o LinkedIn/Instagram": a IA escreve na voz dele (perfil do
  cofre), mostra o rascunho e a imagem escolhida da galeria; ao aprovar, abre o app pelo
  compartilhamento (C3) e, com Acessibilidade (C4), preenche e para no botão Publicar
  perguntando "Posso publicar?". Histórico das postagens no cofre (`Histórico/Postagens.md`).

## C7 — Crescer com o uso
- Receitas: cada sequência de ações em um app que deu certo e foi confirmada vira uma receita
  (app, intenção, passos com seletores por texto/id). Na próxima vez, a receita é reutilizada
  (mais rápido e barato); se a tela mudou, a IA refaz e a receita é atualizada.
- Sugestões: com o histórico de uso, ele propõe atalhos e rotinas ("toda segunda você pede a
  agenda; quer que eu leia às 8h?") — só ativa com o "sim" dele.
- Pedidos que ele ainda não sabe fazer viram "melhoria" na lista do PC (T36).

## C8 — Compilar, instalar e atualizar
- `celular/` com Gradle wrapper; assinatura com keystore local (fora do git; senha no
  Gerenciador de Credenciais). O PC serve o APK mais novo em `GET /apk`; o app avisa "há uma
  versão nova" e abre o instalador do Android. Primeira instalação: QR com link do APK ou
  `adb install` por depuração sem fio.
- Instalador (T38): passos opcionais JDK 17, Android SDK command-line tools e Tailscale.

## Ordem de execução atualizada
(T26 ‖ T30) → T23 → T37 → T33 → T35 → T34 → T36 → T16 → C1 → C2 → C3 → C4 → C5 → C6 → C7 → C8
→ T28 → T17 → T31 → T29 → T32 → T27 → T38.
(T38 fica por último de propósito: o instalador precisa cobrir tudo o que existir; o modo
`-Verificar` pode ser antecipado se for útil.)
