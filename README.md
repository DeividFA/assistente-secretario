# Assistente Secretário

Um secretário pessoal que você comanda pela voz, no PC com Windows e no celular Android.
Ele faz as tarefas chatas e repetitivas no seu lugar, como um assistente humano faria:

- entra em sites, compara opções e preenche cadastros, inscrições e questionários;
- usa o computador como um usuário avançado: abre programas, pastas e o navegador, lê a tela,
  clica e digita;
- cuida da agenda, dos lembretes, dos gastos e de postagens no LinkedIn e no Instagram;
- delega trabalho técnico para outros agentes de IA, como Claude Code, Codex e Gemini;
- aprende sobre você a cada conversa e guarda esse conhecimento numa memória local no Obsidian.

A regra central é que quem decide é sempre você. O secretário pede confirmação antes de enviar
formulários, pagar, publicar, mandar mensagens, apagar ou instalar algo. Ele não concorda com
você só para agradar: datas, preços e fatos são conferidos em fonte confiável antes de serem
afirmados.

---

## Sumário

1. [Visão geral](#visão-geral)
2. [O que ele sabe fazer](#o-que-ele-sabe-fazer)
3. [Arquitetura](#arquitetura)
4. [Estrutura do repositório](#estrutura-do-repositório)
5. [Instalação](#instalação)
6. [Uso no dia a dia](#uso-no-dia-a-dia)
7. [Motores de IA](#motores-de-ia)
8. [Memória no Obsidian](#memória-no-obsidian)
9. [Voz: reconhecimento e fala](#voz-reconhecimento-e-fala)
10. [Multitarefa](#multitarefa)
11. [Trabalhar sem atrapalhar você](#trabalhar-sem-atrapalhar-você)
12. [Backup, diagnóstico e auto-reparo](#backup-diagnóstico-e-auto-reparo)
13. [App Android](#app-android)
14. [Ponte PC ↔ celular](#ponte-pc--celular)
15. [Configuração](#configuração)
16. [Referência técnica](#referência-técnica)
17. [Privacidade e segurança](#privacidade-e-segurança)
18. [Testes](#testes)
19. [Como o projeto foi construído](#como-o-projeto-foi-construído)
20. [Limitações conhecidas](#limitações-conhecidas)

---

## Visão geral

```
                  ┌─────────────────────────── PC (Windows) ───────────────────────────┐
  "Secretário,    │                                                                    │
   abre meu  ──►  │  Microfone ─► Whisper ─► Motor (assistente_voz.py) ─► Fila         │
   LinkedIn"      │                              │                          │          │
                  │                              ▼                          ▼          │
                  │        Memória (Obsidian) ◄─ contexto       Claude / Codex / Gemma │
                  │                              │               / APIs (paralelo)     │
                  │                              ▼                          │          │
                  │          SQLite (logs, fila, bugs) ◄────────────────────┘          │
                  │                              │                                     │
                  │   App Electron (interface) ◄─┤─► Voz (Windows / Piper / Edge)      │
                  │                              │                                     │
                  │                     Ponte HTTP/WS (rede local / Tailscale)         │
                  └──────────────────────────────┼─────────────────────────────────────┘
                                                 │
                  ┌──────────── Celular (Android) ┴────────────────────────────────────┐
                  │  App Secretário: conversa, voz, agenda, gastos, postagens,          │
                  │  operação de apps (Acessibilidade, sem apps de banco)               │
                  │  Sem PC alcançável → IA na nuvem com a chave do usuário             │
                  └────────────────────────────────────────────────────────────────────┘
```

O secretário tem três partes:

- **Motor (`voz/`, Python):**
  - ouve o microfone e transcreve com o Whisper;
  - decide o que fazer e executa usando o motor de IA escolhido;
  - fala as respostas e guarda tudo em SQLite e no Obsidian.
- **App do PC (`app/`, Electron):** a interface, no estilo do Discord. Fica sempre disponível na
  bandeja do Windows e inicia junto com o sistema.
- **App do celular (`celular/`, Kotlin):** conversa com o secretário do PC pela ponte. Sem o PC
  ao alcance, usa uma IA na nuvem.

Além disso, o **skill `/secretario`** do Claude Code (em `instalacao/skill/`) orienta o Claude a
agir como secretário: como usar o navegador, a memória, as confirmações e a delegação.

---

## O que ele sabe fazer

### No PC

| Área | O que faz |
|---|---|
| **Navegador** | Abre sites, lê páginas, compara opções e preenche formulários com o Playwright. Para antes de enviar e mostra o que vai mandar. Login, CAPTCHA e códigos de verificação ficam com você. |
| **Computador** | Abre programas, pastas e URLs, lê janelas e preenche campos por UI Automation. Clica, digita e usa atalhos só quando necessário. |
| **Câmera e tela** | Captura a tela ou uma janela específica. Usa a câmera só quando você pede. |
| **Delegar trabalho** | Passa tarefas técnicas longas para outros agentes de linha de comando (código para o Codex, pesquisa ampla para o Gemini), acompanha e revisa o resultado. |
| **Memória** | Aprende fatos e conceitos das conversas e os organiza por assunto no Obsidian, com ligações entre as notas. |
| **Lembretes** | Cria lembretes, que o app mostra como notificação do Windows. |
| **Backup** | Faz uma cópia verificada do banco, das configurações e do cofre todo dia, e restaura com a sua confirmação. |
| **Auto-reparo** | Detecta bugs, avisa, pede a sua orientação e se corrige pelo Codex, com testes, só depois do seu "sim". |
| **Multitarefa** | Recebe vários pedidos, ordena por prioridade, divide entre motores e fala as respostas uma de cada vez. |

### No celular

| Área | O que faz |
|---|---|
| **Conversa e voz** | Fala e ouve em português, pelo app, por um widget, por um bloco nas configurações rápidas ou por um atalho. |
| **Agenda e atalhos** | Lê e cria eventos no Google Agenda, cria alarmes e timers, abre mapas e prepara rascunhos de mensagem e e-mail. |
| **Operar apps** | Toca, digita e rola dentro de outros apps pela Acessibilidade do Android. **Apps de banco e finanças são bloqueados.** |
| **Gastos** | Registra gastos por voz ("gastei 45 no mercado"), por foto do comprovante, pelas notificações de compra (opcional) ou por CSV. |
| **Postagens** | Escreve no seu estilo, mostra o rascunho e só publica depois de "Posso publicar?". |
| **Crescer com o uso** | Transforma tarefas que deram certo em receitas reaproveitáveis e sugere rotinas a partir dos seus hábitos. |

---

## Arquitetura

### Fluxo de um pedido por voz

1. **Escuta:** o `Microfone` (`comum.py`) fica aberto em modo compartilhado e detecta fala por
   energia. Antes, ele calibra o ruído do ambiente.
2. **Transcrição:** o Whisper `small` roda localmente na CPU, ou na nuvem (Groq ou OpenAI) se
   você configurar. O reconhecimento recebe as suas palavras-chave (*hotwords*) e o vocabulário
   corrige erros conhecidos. Por exemplo, "linketim" vira LinkedIn e "gemão" vira Gemma.
3. **Ativação:** o motor só age se ouvir "secretário", ou nos segundos seguintes a uma resposta,
   para você responder perguntas como "Posso enviar?".
4. **Controle ou tarefa:** comandos curtos, como trocar de motor, cancelar, reiniciar, voz ou
   backup, são tratados na hora. O resto vira tarefa.
5. **Fila:** o pedido recebe uma prioridade ("urgente" vem antes, "quando puder" vai para o fim).
   Pedidos com vários assuntos são divididos em tarefas separadas.
6. **Despacho:** cada tarefa vai para um motor com vaga livre e leva o contexto de memória
   relevante, buscado no Obsidian.
7. **Execução:** o motor de IA usa as ferramentas (navegador, computador, delegação…) e devolve
   a resposta.
8. **Fala:** as respostas entram numa fila de fala e são ditas uma de cada vez. Durante
   chamadas, elas aparecem só na tela.
9. **Aprendizado:** em segundo plano, o Gemma extrai conceitos e fatos da conversa e grava no
   cofre.

### Componentes do motor (`voz/`)

| Módulo | Papel |
|---|---|
| `assistente_voz.py` | Orquestrador: escuta, comandos, fila, despacho, fala, IPC com o app |
| `comum.py` | Microfone, transcrição (Whisper local ou nuvem) e cliente do processo de fala |
| `vocabulario.py` | Palavras-chave, correções de transcrição e ativação tolerante |
| `padrao_fala.py` | Confiança por palavra, pausa adaptativa, idiomas e perfil de fala |
| `vozes.py`, `falar_proc.py` | Catálogo, download e síntese das vozes (Windows, Piper, Edge) |
| `fila.py` | Fila de tarefas com prioridade no SQLite |
| `provedores.py` | Registro de motores e chaves de API (Gerenciador de Credenciais) |
| `motores_cli.py` | Adaptadores dos agentes de linha de comando (Claude, Codex, Gemini, Qwen) |
| `agente_local.py`, `acoes.py` | Loop de ações para modelos de API e catálogo de ações seguras |
| `delegacao.py` | Delegação de trabalho a agentes CLI em segundo plano |
| `memoria.py`, `extrator.py` | Cofre do Obsidian: índice, busca, contexto, aprendizado |
| `registro.py` | SQLite: eventos, tarefas, bugs |
| `backup.py` | Backup verificado, rotação e restauração |
| `diagnostico.py`, `reparo.py` | Captura de bugs, verificação de saúde, auto-reparo e verificação da instalação |
| `dispositivos.py` | Detecta outros programas usando o microfone (chamadas) |
| `segundo_plano.py` | UI Automation, captura de janela e espera de ociosidade |
| `ponte.py`, `gastos.py`, `lembretes.py` | Servidor para o celular e os dados que ele sincroniza |
| `sentidos_mcp.py` | Servidor MCP com as ferramentas do computador para o Claude |

### App do PC (`app/`)

O app em Electron inicia o motor como `python assistente_voz.py --ipc` e conversa com ele por
linhas JSON (stdin e stdout). Ele oferece:

- conversas salvas e motor escolhido num menu;
- cartão de voz com nível do microfone, mudo e silêncio;
- painéis de fila, vozes, problemas e Configurações;
- apresentação inicial e calibração de voz.

Ele também fica na bandeja do Windows, com ícone por estado. Atalhos: **Ctrl+Shift+Espaço**
(falar agora) e **Ctrl+Shift+S** (mostrar ou esconder).

---

## Estrutura do repositório

```
assistente-secretario/
├── voz/                  Motor em Python (veja a tabela acima)
│   ├── tests/            Testes do motor (pytest)
│   ├── ferramentas/      Utilitários (ex.: benchmark do Whisper)
│   ├── voz_prompt.md     Instruções do modo voz para o Claude
│   ├── config.exemplo.json
│   └── requirements.txt  Dependências com versões fixas
├── app/                  Interface Electron (main.js, renderer.js, index.html, estilo.css)
├── celular/              App Android (Gradle, Kotlin, Compose) + instalar.ps1
├── instalacao/
│   ├── instalar.ps1      Instalador idempotente (-Verificar só confere)
│   ├── skill/SKILL.md    Skill /secretario do Claude Code
│   ├── agente/           Subagente "secretario"
│   └── cofre_modelo/     Esqueleto do cofre do Obsidian, sem dados pessoais
└── TAREFAS.md            Especificação de cada tarefa do projeto
```

Ficam **fora** do repositório (`.gitignore`): `voz/.venv`, `secretario.db`, `config.json`,
`correcoes.json`, `lembretes.json`, logs, capturas de tela, modelos de voz baixados, `sinais/`,
travas, builds e keystores do Android.

---

## Instalação

### Requisitos

- Windows 10 ou 11 com `winget`.
- Contas no Claude Code e no Codex, para os motores principais.
- Opcional: chaves de API (Grok, GPT, Gemini, DeepSeek, Mistral, OpenRouter, Groq).
- Para o celular: Android 10 ou mais novo. Operar outros apps exige Android 14 ou mais novo.

### Instalador automático

```powershell
git clone https://github.com/<usuario>/assistente-secretario "$HOME\.claude\secretario"
cd "$HOME\.claude\secretario"
powershell -ExecutionPolicy Bypass -File instalacao\instalar.ps1
```

Ele confere cada passo e só instala o que falta:

1. Python 3.12, Node LTS, Git, Ollama e Obsidian, via `winget`.
2. O ambiente Python `voz\.venv` com o `requirements.txt` e as dependências do app (`npm ci`).
3. Os CLIs `@anthropic-ai/claude-code` e `@openai/codex`.
4. Os servidores MCP no escopo do usuário (`playwright` e `sentidos`) e o Chromium do
   Playwright.
5. O skill e o agente em `~\.claude\` (versões diferentes ficam guardadas como `.bak`).
6. O cofre `Documents\Secretario`, criado a partir do modelo e registrado no Obsidian sem
   substituir os seus outros cofres.
7. Os modelos: `gemma3:4b` (Ollama) e Whisper `small`.
8. O `config.json` padrão, o atalho na área de trabalho e o início com o Windows.
9. Uma verificação final em tabela.

| Opção | Efeito |
|---|---|
| `-Verificar` | Só confere e mostra a tabela, sem instalar nada |
| `-SemModelos` | Pula o Gemma, o Whisper e as vozes |
| `-Voz faber` | Baixa também a voz neural Piper "Faber" |
| `-Celular` | Instala o JDK 17 e o Android SDK, para compilar o app (o `JAVA_HOME` do usuário é preservado) |
| `-Tailscale` | Instala o Tailscale, para usar o celular fora de casa |

### Passos manuais (de propósito)

- Entrar no Claude Code (`claude`) e no Codex (`codex login`).
- Colocar as chaves de API em **Configurações**. Elas vão para o Gerenciador de Credenciais do
  Windows e nunca para arquivos.
- Fazer login no Tailscale, se for usar o celular fora de casa.

---

## Uso no dia a dia

### Falar com ele

Diga **"Secretário, …"** e o pedido. Depois de uma resposta, você tem alguns segundos para
continuar sem repetir "secretário". Também dá para digitar no app ou apertar
**Ctrl+Shift+Espaço**.

### Comandos de controle

| Diga | O que acontece |
|---|---|
| "usa o Claude" / "usa o Codex" / "usa o Gemma" / "usa o GPT"… | Troca o motor |
| "cancela" / "para" / "cancela tudo" / "cancela a 3" | Cancela tarefas |
| "nova conversa" | Começa uma sessão nova |
| "reinicia" / "reinicia tudo" | Reinicia o motor ou o app inteiro |
| "desligar" | Encerra o motor |
| "usa a voz Faber" / "troca a voz para Francisca" | Troca a voz (pergunta se pode baixar, quando precisa) |
| "faz um backup" / "restaura o backup" | Backup na hora / restauração com confirmação |
| "o que deu errado?" / "corrige o problema" | Lista os problemas / pede o auto-reparo |
| "anota uma melhoria: …" | Registra uma ideia de melhoria |
| "urgente: …" / "… quando puder" | Define a prioridade do pedido |

### Exemplos de pedidos

- "Secretário, entra no site do concurso X e vê se as inscrições estão abertas."
- "Secretário, preenche essa inscrição com os meus dados e me mostra antes de enviar."
- "Secretário, abre o meu LinkedIn e procura vagas de backend .NET remoto."
- "Secretário, pede para o Codex corrigir o teste que está falhando no projeto Y."
- "Secretário, me lembra de pagar a conta de luz amanhã às 9h."

---

## Motores de IA

| Motor | Tipo | Como roda | Observações |
|---|---|---|---|
| Claude Code | Agente CLI | `claude -p` com stream JSON e sessões | Motor principal: usa navegador, computador e MCPs |
| Codex | Agente CLI | `codex exec` | Ótimo para código; também usado no auto-reparo |
| Gemini CLI | Agente CLI | `gemini -p` | Precisa do CLI instalado e do login Google |
| Qwen | Agente CLI | `qwen -p` | Depende da configuração do usuário |
| Grok, GPT, Gemini, DeepSeek, Mistral, OpenRouter | API | API compatível com OpenAI + catálogo de ações | Precisam de chave |
| Gemma 3 (4b) | Local | Ollama no próprio PC | Nada sai do PC; mais lento em CPU |

Você troca o motor por voz, pelo menu no topo do chat ou pela bandeja. Os motores de API usam um
catálogo de ações seguras (abrir, pesquisar, ler a tela, comandos só de leitura no PowerShell…).
As ações sensíveis pedem confirmação.

---

## Memória no Obsidian

O cofre fica em `Documents\Secretario` e é Markdown puro. Você também pode ler e editar as notas
no Obsidian.

| Onde | Conteúdo |
|---|---|
| `00 - Índice.md` | Resumo essencial e mapa |
| `Perfil/` | Dados pessoais, documentos, formação, experiência, aprendizados, fala |
| `Preferências/` | Regras de trabalho, estilo, correções |
| `Assuntos/` | Um hub por assunto (Religião, Trabalho, Tecnologia, Finanças…) |
| `Conceitos/` | Uma nota por conceito, ligada ao hub e às notas relacionadas |
| `Histórico/` | Inscrições, postagens |
| `Diário/` | O que foi feito em cada dia |
| `Finanças/` | Resumo mensal dos gastos, só com totais por categoria |

**Como a memória funciona**

- **Antes de cada pedido:** o motor busca as notas relevantes, pelo título, pelos apelidos e pelo
  resumo, com singular e plural. Ele inclui também as notas ligadas a elas, e esse contexto vai
  junto com o pedido.
- **Depois de cada resposta:** o Gemma extrai conceitos e fatos. Exemplo: "Jesus Cristo" entra
  em **Religião** e se liga a **Bíblia**. Assim, assuntos relacionados se encontram sem
  precisar reler o cofre inteiro.
- **Filtros:** comandos operacionais ("abre o bloco de notas") e "fatos" sobre ações não viram
  memória.

---

## Voz: reconhecimento e fala

**Reconhecimento**

- O Whisper `small` roda localmente, com detecção de fala e palavras-chave. A transcrição na
  nuvem (Groq ou OpenAI) é opcional, e o local entra como reserva se ela falhar.
- **Vocabulário:** correções fixas mais as que você ensina. Por exemplo, "David" vira Deivid e
  "cloud" vira Claude.
- **Confiança por palavra:** as palavras incertas aparecem sublinhadas para você corrigir com o
  lápis. O secretário aprende a pronúncia, mas palavras comuns do português nunca são trocadas.
- **Pausa adaptativa:** a cada 30 falas, ele ajusta o tempo de espera ao fim da frase.
- **Idiomas:** com `"idiomas": ["pt", "en"]`, ele tenta o inglês quando a confiança no português
  é baixa.
- **Calibrar voz:** uma tela com três etapas, o ruído do ambiente, as palavras-chave com correção
  automática e a medição da sua pausa.

**Fala**

| Voz | Tipo | Observações |
|---|---|---|
| Windows (Maria) | SAPI, local | Padrão |
| Piper: Faber, Cadu, Jeff, Edresson (pt-BR), Tugão (pt-PT), Amy (en) | Neural, local | Baixadas pelo painel Voz (cerca de 20 a 63 MB) |
| Edge: Francisca, Antonio, Thalita | Neural, online | O texto é enviado à Microsoft |

O processo de fala fica aberto, o modelo carrega uma vez e a fala pode ser interrompida. Se a voz
escolhida falhar, ele usa a voz do Windows e nunca fica mudo.

**Microfone compartilhado**

- **Mudo:** fecha o dispositivo de verdade.
- **Durante chamadas** (Discord, Teams, Zoom, Meet): o secretário solta o microfone e não fala em
  voz alta.
- **Modo sob demanda:** o microfone só abre pelo atalho.
- **Fone desconectado:** ele reabre o microfone sozinho.

---

## Multitarefa

- Cada pedido vira uma tarefa na fila do SQLite, com prioridade 0 (urgente) a 3 (quando puder).
- O despachante escolhe um motor com vaga para cada tarefa: primeiro o motor escolhido, depois
  `motores_paralelos`. As vagas são configuráveis, por exemplo 2 tarefas no Claude e 1 no Codex.
- Exemplo: com o Claude ocupado, a próxima tarefa vai para o Codex, e as duas rodam ao mesmo
  tempo.
- **Exceção de privacidade:** com o **Gemma** escolhido, as tarefas esperam a vez dele em vez de
  irem para a nuvem.
- As respostas são faladas **uma de cada vez**, com o prefixo "Sobre <pedido>:" quando há mais de
  uma rodando.

---

## Trabalhar sem atrapalhar você

O secretário pode trabalhar enquanto você usa o computador:

1. **Sites:** pelo Playwright, que não usa o seu mouse nem o seu teclado.
2. **Programas:** ele lê janelas (`ler_janela`), preenche campos (`preencher_campo`), aperta
   botões (`acionar`) e captura janelas (`capturar_janela`) por UI Automation, sem trazer a
   janela para frente.
3. **Mouse e teclado de verdade, só em último caso:**
   - ele espera você ficar 2 s sem mexer (desiste depois de 2 minutos);
   - no fim, devolve o cursor e a área de transferência;
   - a janela só volta para frente depois da sequência de ações, para o texto nunca cair na sua
     janela.

---

## Backup, diagnóstico e auto-reparo

### Backup (`backup.py`)

- **Conteúdo:**
  - cópia consistente do SQLite pela API de backup, que funciona com o motor rodando;
  - `config.json`, `correcoes.json` e `lembretes.json`;
  - um zip do cofre.
- **Verificação:** `integrity_check` e um manifesto com SHA-256 de cada arquivo.
- **Quando:** ao iniciar, se o último backup tiver mais de 24 h; antes de cada auto-reparo; antes
  de restaurar; e por pedido.
- **Retenção:** 7 diários, 4 semanais e 6 mensais. Os backups feitos antes de reparos ficam
  30 dias.
- **Onde:** em `%USERPROFILE%\Backups\Secretario`, mais uma pasta extra opcional, como o OneDrive.
- **Restaurar:** "restaura o backup" mostra a data e pede confirmação. Antes, ele guarda os dados
  atuais.
- **Banco corrompido:** o motor entra em modo de recuperação e oferece restaurar.
- **Chaves de API:** não entram no backup; ficam no Gerenciador de Credenciais.

### Diagnóstico e reparo (`diagnostico.py`, `reparo.py`)

- **Registro de problemas:** exceções, quedas do motor e sintomas viram registros no SQLite,
  agrupados por assinatura. Sintomas são, por exemplo, o mesmo erro de motor 3 vezes ou
  5 transcrições vazias seguidas.
- **Verificação de saúde:** ao iniciar, ele confere banco, cofre, Ollama, microfone e disco. Uma
  vez por dia, quando você está ocioso, roda todos os testes.
- **Aviso:** "Encontrei um problema: X. Quer que eu tente corrigir? Se tiver alguma orientação,
  pode falar."
- **Auto-reparo, só com a sua aprovação:**
  1. faz um backup;
  2. cria a branch `reparo/<id>`;
  3. o Codex corrige e escreve um teste que reproduz o problema;
  4. os testes rodam;
  5. a correção entra por merge `--ff-only`;
  6. ele pede para reiniciar.
- **Proteções do reparo:**
  - nunca toca nos seus dados;
  - nunca faz `push`;
  - no máximo 2 tentativas por problema;
  - se o motor cair 2 vezes em 5 minutos depois de um reparo, o app desfaz a correção sozinho.

---

## App Android

Fica em `celular/`. Usa Kotlin e Jetpack Compose, com minSdk 29 e targetSdk 35.

| Tela ou recurso | Detalhes |
|---|---|
| Conversa | Texto e voz (`SpeechRecognizer` e `TextToSpeech` em pt-BR). Indicador "PC" ou "Nuvem" |
| Pareamento | Lê o QR do botão "Conectar celular" do PC (CameraX e ML Kit) |
| Roteador | Tenta o PC em até 1,5 s; sem resposta, usa a IA na nuvem configurada (chave cifrada no Keystore) |
| Ações | Agenda (`CalendarContract`), alarmes, mapas, rascunhos, compartilhar. Permissões pedidas só no primeiro uso |
| Acessibilidade | Lê e opera o app em primeiro plano, com confirmação antes de publicar, enviar, comprar ou apagar. Pausa quando você toca na tela. Botão "Parar" |
| Bloqueio financeiro | 49 pacotes fixos de bancos, fintechs, carteiras e cripto, mais regras pelo nome do pacote. Você pode acrescentar apps, mas não remover os de fábrica. Campos de senha nunca são lidos. Telas protegidas (`FLAG_SECURE`) interrompem a automação |
| Gastos | Voz, foto (OCR no aparelho), notificações (desligado por padrão, só dos apps que você marcar, guarda só valor, local e data) e CSV. Valores em centavos |
| Postagens | Rascunho no seu estilo, editável, com "Posso publicar?". Histórico no cofre |
| Crescer com o uso | Receitas guardam só os passos, nunca o que foi digitado. Rotinas sugeridas depois de 3 ocorrências, ativadas só com o seu "sim" |
| Atualização | Baixa o APK novo pela ponte e confere o SHA-256 antes de abrir o instalador |

### Compilar e instalar

```powershell
cd celular
.\instalar.ps1                                  # compila (JDK 17) e instala por adb
.\instalar.ps1 -Parear 192.168.0.10:37123 123456  # pareia a depuração sem fio antes
```

No Android 13 ou mais novo, apps instalados por fora da loja precisam de **"Permitir
configurações restritas"** (em Informações do app) antes de ligar a Acessibilidade.

---

## Ponte PC ↔ celular

`voz/ponte.py` é um servidor HTTP e WebSocket (aiohttp) dentro do motor:

- **Desligada por padrão:** liga e desliga pelo botão "Conectar celular".
- **Onde escuta:** só nos IPs da rede local privada e do Tailscale (`100.64.0.0/10`), nunca em
  `0.0.0.0`. Endereços inativos são ignorados.
- **Pareamento:** por QR com um token aleatório por aparelho, guardado como hash. Um QR que não é
  usado em 10 minutos expira. Aparelhos podem ser revogados.
- **Limites e auditoria:** 60 requisições por minuto por aparelho, e tudo é registrado.

| Método | Rota | Função |
|---|---|---|
| WS | `/eventos` | Eventos do motor (mensagens, estado, fila…) |
| POST | `/comando` | Pedido do celular para a fila do PC |
| GET | `/memoria/contexto?q=` | Contexto de memória para um pedido |
| POST | `/memoria/fatos` | Fatos aprendidos no celular |
| GET | `/memoria/perfil-estilo` | Resumo de estilo para postagens (sem documentos, contatos nem filiação) |
| GET/POST | `/lembretes` | Lembretes sincronizados |
| GET/POST | `/gastos` | Gastos (com deduplicação) e nota mensal no cofre |
| POST | `/postagens` | Registro das postagens publicadas |
| POST | `/bugs` | Problemas e melhorias vindos do celular |
| GET | `/apk`, `/apk/versao` | APK mais novo, com versão e SHA-256 |

Todas as rotas exigem `Authorization: Bearer <token>`. No Wi-Fi de casa, o tráfego é HTTP sem
criptografia. Fora de casa, use o Tailscale, que criptografa tudo.

---

## Configuração

Fica em `voz/config.json` (criado a partir de `config.exemplo.json`). Quase tudo também pode ser
mudado pelo painel **Configurações**.

| Chave | Padrão | Significado |
|---|---|---|
| `microfone` | `null` | Índice do microfone (`null` = padrão do Windows) |
| `modo_microfone` | `"continuo"` | `continuo` ou `sob_demanda` |
| `mic_em_chamada` | `"liberar"` | Solta o microfone (`liberar`) ou não (`compartilhar`) durante chamadas |
| `modelo_whisper` | `"small"` | Modelo local do Whisper |
| `transcricao` | `"local"` | `local`, `groq` ou `openai` |
| `palavra_ativacao` | `"secretário"` | Palavra de ativação |
| `janela_conversa` | `15` | Segundos para responder sem repetir a palavra de ativação |
| `pausa_fala` / `pausa_auto` | `1.4` / `true` | Pausa que encerra a frase e se ela se ajusta sozinha |
| `idiomas` | `["pt"]` | Idiomas aceitos |
| `voz` / `velocidade_fala` | `"windows"` / `190` | Voz de resposta e velocidade |
| `motores_paralelos` | `["claude","codex","gemma"]` | Ordem para distribuir tarefas |
| `vagas` | `{"claude":2,"codex":1,…,"api":2}` | Tarefas simultâneas por motor |
| `pasta_backup` / `pasta_backup_extra` | `~\Backups\Secretario` / `null` | Destinos do backup |
| `ponte_ativa` | `false` | Ponte com o celular |
| `pasta_apk` | `celular/app/build/outputs/apk` | De onde a ponte serve o APK |

As **chaves de API** não ficam aqui: use Configurações. Elas vão para o Gerenciador de
Credenciais, no serviço `secretario`.

---

## Referência técnica

### Ferramentas MCP (`sentidos`)

| Grupo | Ferramentas |
|---|---|
| Sentidos | `ouvir`, `falar`, `foto_camera`, `captura_tela` |
| Por trás (sem foco) | `capturar_janela`, `ler_janela`, `preencher_campo`, `acionar` |
| Físicas (esperam você parar) | `clicar`, `arrastar`, `digitar`, `teclas`, `rolar`, `focar_janela` |
| Sistema | `abrir`, `janelas`, `lembrete`, `listar_lembretes`, `reiniciar_secretario` |
| Delegação | `delegar`, `resultado_delegacao`, `cancelar_delegacao`, `agentes_disponiveis` |
| Voz | `vozes_disponiveis`, `baixar_voz`, `usar_voz`, `aprender_pronuncia` |
| Manutenção | `fazer_backup`, `listar_backups`, `restaurar_backup`, `listar_bugs`, `detalhe_bug`, `corrigir_bug` |

### IPC do app ↔ motor (linhas JSON)

- **Comandos (app → motor):**
  - conversa e controle: `texto`, `cancelar`, `mudo`, `silencio`, `sessao`, `ouvir_agora`,
    `sair`;
  - motores: `motor`, `chave`;
  - vozes: `vozes`, `voz`, `baixar_voz`, `remover_voz`, `amostra_voz`;
  - microfone: `modo_microfone`;
  - configurações e correção: `config`, `configuracoes`, `correcao`;
  - manutenção: `backup_agora`, `verificar_saude`, `bugs`, `corrigir_bug`, `ignorar_bug`;
  - celular: `ponte`, `revogar_aparelho`;
  - apresentação e calibração: `perfil_atual`, `perfil_inicial`, `ditar`, `calibrar_voz`.
- **Eventos (motor → app):**
  - conversa: `mensagem`, `estado`, `ferramenta`, `fila`, `sessao`, `transcricao`, `ditado`;
  - motores e vozes: `motores`, `vozes`, `download_voz`;
  - microfone: `microfone`, `nivel`, `resposta_silenciosa`;
  - memória e perfil: `memoria`, `perfil_atual`, `perfil_salvo`;
  - manutenção: `bugs`, `reparo`, `configuracoes`, `config_resultado`, `correcao`,
    `calibracao`;
  - celular: `ponte`;
  - ciclo de vida: `reiniciar`, `saindo`, `nova_conversa`, `erro`.

### Banco SQLite (`voz/secretario.db`, modo WAL)

| Tabelas | Conteúdo |
|---|---|
| `eventos`, `tarefas` | Log e histórico de tarefas |
| `fila` | Multitarefa |
| `delegacoes` | Trabalhos delegados a agentes |
| `bugs` | Problemas e melhorias |
| `falas` | Padrão de fala |
| `aparelhos`, `pedidos_celular` | Ponte com o celular |
| `gastos` | Gastos, em centavos |

---

## Privacidade e segurança

- **Local primeiro:** a memória, o banco e as gravações ficam no PC. Com o Gemma, nada sai da
  máquina.
- **Confirmação:** antes de enviar inscrições, pagar, aceitar termos, criar contas, mandar
  mensagens em seu nome, apagar ou mudar o sistema.
- **Nunca:** digitar ou guardar senhas, guardar dados de cartão, resolver CAPTCHA ou usar códigos
  de verificação. Isso é com você.
- **Câmera:** só quando você pede explicitamente.
- **Conteúdo de sites:** é tratado como dado, não como instrução.
- **Sites que proíbem IA:** ele avisa uma vez o risco. Se você mandar continuar, continua, porque
  a responsabilidade pelo envio é sua. Em provas, você dita as respostas e ele só transcreve.
- **Chaves de API:** ficam no Gerenciador de Credenciais e nunca aparecem na interface, nos logs
  ou nos eventos.
- **Celular:** apps financeiros bloqueados, senhas nunca lidas, perfil enviado à nuvem sem
  documentos e contatos, gastos com números longos mascarados.
- **Repositório:** nenhum dado pessoal, banco, log, configuração ou chave é versionado.

---

## Testes

```powershell
voz\.venv\Scripts\python -m pytest voz\tests        # cerca de 430 testes do motor
cd celular; $env:JAVA_HOME="C:\Program Files\Microsoft\jdk-17..."; .\gradlew.bat testDebugUnitTest assembleDebug
node --check app\main.js; node --check app\renderer.js
powershell -File instalacao\instalar.ps1 -Verificar
```

Os testes usam dispositivos, rede, git e agentes falsos. Nada toca no microfone, no cofre real,
no repositório real ou na internet.

---

## Como o projeto foi construído

O desenvolvimento seguiu um ciclo de *especificar → implementar → revisar → testar de verdade*:

1. Cada recurso virou uma tarefa pequena e bem definida no `TAREFAS.md`, com os arquivos, o que
   fazer e os testes esperados.
2. O **Codex** implementou cada tarefa (`codex exec`).
3. O **Claude Code** revisou o diff, rodou os testes e fez um teste real: motor, microfone, rede,
   compilação Android, cópias do cofre. Depois corrigiu o que achou e fez o commit.

Muitas correções vieram desses testes reais. Exemplos:

- o microfone era derrubado por avisos passageiros do áudio;
- um IP de cabo desconectado derrubava a ponte;
- três apps financeiros brasileiros passavam pelo bloqueio;
- o resumo de perfil vazava campos sensíveis.

---

## Limitações conhecidas

- **Desempenho em CPU:** sem placa de vídeo, o Whisper leva cerca de 4,5 s por frase e o Gemma
  gera cerca de 7 tokens por segundo.
- **Celular:** operar outros apps exige Android 14 ou mais novo. No Wi-Fi local, a ponte usa HTTP
  sem criptografia.
- **Instalação:** ainda não há instalador empacotado (.exe); o app roda da pasta do projeto.
- **Motores por API:** o Gemini CLI, o Qwen e os motores por API dependem de instalação ou chaves
  do usuário.
