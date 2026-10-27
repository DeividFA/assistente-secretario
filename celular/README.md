# Secretário Android — C2 a C8

Base pessoal em Kotlin/Compose, tema escuro/menta, Android 10 ou superior.
`RegistroAcoes` expõe as ações C3 à nuvem por chamadas de função.
A C4 acrescenta operação de apps não financeiros por Acessibilidade.

## Compilar e instalar (revisor)

Pré-requisitos: JDK 17, Android SDK com `platforms;android-35`, build-tools e
platform-tools; `ANDROID_HOME` apontando para o SDK (ou `sdk.dir` em
`local.properties`). Aceite as licenças com `sdkmanager --licenses`.

O wrapper incluído usa Gradle 8.9; o plugin Android é AGP 8.7.3.
No PowerShell 5.1, dentro de `celular/`, o script seleciona o JDK 17 de
`C:/Program Files/Microsoft/jdk-17*`, compila e instala por adb:

```powershell
.\instalar.ps1                         # USB, dispositivo autorizado
.\instalar.ps1 -Dispositivo SERIAL     # escolher entre vários aparelhos
.\instalar.ps1 -Parear 192.168.1.20:37001 123456 -Conectar 192.168.1.20:39001
.\instalar.ps1 -Conectar 192.168.1.20:39001 -Tipo Release
```

No Android 11+, habilite **Opções do desenvolvedor → Depuração sem fio → Parear
com código**. A porta de pareamento e a porta de conexão são diferentes; use as
exibidas no celular. O código é temporário. Para USB, habilite depuração USB e
aceite a chave do PC. O script usa adb do PATH ou do SDK configurado em
`ANDROID_HOME`, `ANDROID_SDK_ROOT` ou `local.properties`; falhas interrompem a instalação.

Em Linux/macOS: `chmod +x gradlew`, `./gradlew testDebugUnitTest assembleDebug` e
`adb install -r app/build/outputs/apk/debug/app-debug.apk`.
O APK debug usa a assinatura local de desenvolvimento. Para instalar manualmente,
copie o APK e habilite a instalação de fontes desconhecidas para o app que o abrir.
Nenhum comando Gradle foi executado durante a implementação.

### Versão e assinatura local

Edite `celular/versao.properties` antes de compilar: `versionCode` deve ser um
inteiro positivo crescente e `versionName` é o nome exibido. Debug e release usam
esses mesmos valores. O Android só aceita atualização com a mesma chave de assinatura;
guarde o keystore e seu backup fora do repositório. Trocar de debug para release
exige reinstalação se as chaves forem diferentes, com perda dos dados locais.

Crie sua chave com o `keytool` do JDK (ele pede as senhas interativamente):

```powershell
keytool -genkeypair -keystore "$env:USERPROFILE\secretario-release.jks" -alias secretario -keyalg RSA -keysize 3072 -validity 10000
```

Configure estas variáveis no ambiente do processo que compila:
`SECRETARIO_STOREFILE`, `SECRETARIO_STOREPASSWORD`, `SECRETARIO_KEYALIAS`,
`SECRETARIO_KEYPASSWORD`. Cada variável tem prioridade sobre a propriedade
correspondente em `celular/keystore.properties` (ignorado pelo git):

```properties
storeFile=C:/Users/SEU_USUARIO/secretario-release.jks
storePassword=SENHA_LOCAL
keyAlias=secretario
keyPassword=SENHA_LOCAL
```

Use barras `/` nos caminhos desse arquivo; caminhos relativos partem de `celular/`.
Prefira obter as senhas do Gerenciador de Credenciais para o ambiente da sessão;
o projeto não grava senhas no código nem cria uma chave automaticamente.
Sem arquivo de chave ou credenciais completas, `assembleRelease` gera release
**não assinado** e o script recusa instalá-lo. Debug continua com a chave de desenvolvimento.

### Atualizar pela ponte

Em `voz/config.json`, `pasta_apk` escolhe a pasta de publicação; o padrão é
`celular/app/build/outputs/apk`. Caminhos relativos partem da raiz do repositório.
A ponte procura recursivamente o `.apk` com modificação mais recente (desempate
pelo caminho) e exige o `output-metadata.json` gerado pelo Gradle na mesma pasta,
com `outputFile`, `versionCode` e `versionName` do APK. Para publicar em outra pasta,
copie ambos após a compilação, sem modificar arquivos enquanto são servidos.
Publique somente a variante assinada com a chave usada no celular.

`GET /apk/versao` retorna `{versionCode, versionName, sha256}`; `GET /apk`
retorna os bytes com `X-Version-Code`, `X-Version-Name` e `X-SHA256`.
Ambas exigem o Bearer do aparelho e mantêm o limite de requisições e a auditoria
da ponte. Pasta sem APK retorna 404; metadados ausentes/inválidos retornam 503.
O hash é calculado sobre os bytes servidos, sem usar o arquivo de versão ainda não compilado.

Ao abrir o app pareado, ele consulta no máximo uma vez a cada 24 horas (inclusive
tentativas sem conexão); **Verificar atualização** permite consulta manual.
A comparação usa `versionCode`. Quando há versão nova, **Baixar e instalar** salva
o APK no cache privado e confere SHA-256 antes de abrir o instalador por FileProvider.
Se a publicação mudou entre consulta e download, a instalação é bloqueada e é preciso
consultar novamente. Na primeira atualização, permita **Instalar apps desconhecidos**
para o Secretário; ao voltar, ele abre o instalador. A instalação sempre exige a
confirmação do Android. O hash verifica integridade; a assinatura é validada pelo Android.
Para primeira instalação, use o script adb acima; o QR de pareamento não é um link
público de download, pois `/apk` exige autenticação.

Verificações para o revisor (não executadas nesta implementação):

```powershell
# Na raiz do repositório:
voz/.venv/Scripts/python.exe -m pytest voz/tests/test_ponte.py -q
# Em celular/:
.\gradlew.bat testDebugUnitTest assembleDebug assembleRelease
```

## Uso

1. No PC, ligue a ponte e escolha **Conectar celular**. No Android, abra **Config. →
   Ler QR do PC** e autorize a câmera. O QR inicial expira em dez minutos sem uso.
2. Use a mesma LAN; fora de casa, mantenha Tailscale ativo no PC e no Android.
   O app tenta LAN e depois Tailscale dentro de uma janela total de 1,5 s.
3. Escolha Gemini, GPT, Grok ou OpenRouter, informe sua chave e salve. A URL base e
   o modelo são editáveis para acompanhar a disponibilidade da sua conta. A chave
   não é enviada ao PC; ela e o token do pareamento ficam em
   EncryptedSharedPreferences com Android Keystore. Backup do app desabilitado.
4. Digite ou toque **Microfone**. O reconhecimento usa pt-BR, prefere o serviço
   offline do dispositivo (Android 12+) e solicita preferência offline nas demais
   versões. A disponibilidade depende do serviço/modelo instalado; ele pode usar
   rede. As respostas são faladas com TextToSpeech pt-BR.
5. **Guardar** registra um fato em Room. A fila de fatos sobrevive ao fechamento e
   sincroniza em lotes com o PC enquanto o app está aberto, a cada dez segundos.
   Uma falha mantém o lote para nova tentativa; a C1 deduplica os fatos aprendidos.
6. Adicione o widget pela tela inicial, pressione o ícone para o atalho de voz ou
   edite as Configurações rápidas do Android para adicionar o bloco Secretário.
   Todos abrem a conversa e solicitam voz após desbloquear/permissão.

Histórico e fatos pendentes ficam no Room local. Ao usar a nuvem, até vinte mensagens
recentes da conversa são enviadas como contexto ao provedor escolhido.
A conexão WS é mantida com o app
em primeiro plano e reconectada a cada dez segundos. Ao voltar, a C1 só entrega
eventos novos: ela não disponibiliza replay de mensagens ou da fila.

## Contrato e roteamento

QR: JSON `{"host_lan":"192.168.1.5","host_tailscale":"100.80.1.2",
"porta":8765,"token":"<64 caracteres hexadecimais>"}`. Cada host pode ser `null`,
mas pelo menos um precisa existir. São aceitos IPv4 privados/Tailscale, como C1.

HTTP e WS usam `Authorization: Bearer <token>`. O roteador verifica a conexão
autenticada `WS /eventos` em até 1,5 s (se já aberta, exige uma resposta autenticada
de `GET /memoria/contexto?q=` para detectar conexões obsoletas); conectado, envia `POST /comando` com
`{"texto":"..."}` e exige `202 {"tarefas":[...]}`. Esse recibo é um aceite de fila;
a resposta chega pelo WS. Eventos `mensagem` usam `autor`/`texto`, `estado` usa
`estado` e `fila` usa `tarefas` (`id`, `comando`, `status`). Eventos extras são
ignorados. A fila exibida é a da ponte, sem ações de cancelar ou reordenar na C2.

Se o PC não conectar no prazo, a mensagem segue à API OpenAI compatível em
`<base>/chat/completions`. O indicador mostra o último cérebro usado. Há suporte
ao catálogo `tools` e aos retornos `tool_calls`, com escolha somente de nomes
registrados. Não há execução arbitrária de nomes retornados pela IA.
Falha de POST após conectar não repete o comando na nuvem: o PC pode já tê-lo
aceitado. O app informa o erro para o usuário conferir a fila antes de repetir.

A ponte atual usa HTTP/WS sem TLS: use sua LAN confiável ou Tailscale. A nuvem
aceita apenas URL HTTPS. Não há serviço de escuta ou sincronização em segundo plano.

## Versões fixadas

| Componente | Versão |
| --- | --- |
| Gradle / AGP | 8.9 / 8.7.3 |
| Kotlin / plugin Compose | 2.0.21 / 2.0.21 |
| KSP | 2.0.21-1.0.28 |
| Compose BOM | 2024.12.01 |
| SDK mínimo / compilação / alvo | 29 / 35 / 35 |
| Java | 17 |
| Activity / Core / Lifecycle | 1.9.3 / 1.15.0 / 2.8.7 |
| Room | 2.6.1 |
| Coroutines / Serialization JSON | 1.9.0 / 1.7.3 |
| OkHttp | 4.12.0 |
| CameraX / ML Kit barcode-scanning | 1.4.1 / 17.3.0 (modelo embarcado) |
| Security Crypto / JUnit | 1.1.0 / 4.13.2 |

AGP 8.7 suporta SDK 35, Gradle 8.9 e JDK 17 conforme as
[notas oficiais](https://developer.android.com/build/releases/agp-8-7-0-release-notes).
O plugin Compose acompanha a versão do Kotlin conforme a
[documentação Kotlin](https://kotlinlang.org/docs/compose-compiler-migration-guide.html).
O scanner usa a dependência embarcada da
[documentação ML Kit](https://developers.google.com/ml-kit/vision/barcode-scanning/android).

Os testes JVM em `app/src/test/` usam JUnit e relógio virtual de coroutines, sem
Android, câmera, microfone ou serviços reais. Cobrem parse de QR/eventos/aceite,
seleção do cérebro, timeout, falhas e cancelamento. O esquema Room será exportado
por KSP em `app/schemas/` na primeira compilação do revisor.

## Segurança da conexão com o PC
- No Wi-Fi de casa a conversa com o PC usa HTTP sem criptografia (inclusive a chave do
  aparelho). Use só em rede confiável; fora de casa, conecte pelo Tailscale, que criptografa.
- O QR de pareamento expira em 10 minutos se não for usado. Revogue aparelhos perdidos no
  app do PC ("Conectar celular" → lista de aparelhos).

## Ações C3

Na nuvem, há ferramentas para abrir app pelo pacote, ler/criar eventos nos
calendários do Android (incluindo Google Agenda), alarme/timer, mapa/rota,
rascunhos de SMS/WhatsApp/e-mail e compartilhamento de texto/imagem `content://`.
O usuário confirma na interface antes de criar evento ou preparar rascunho;
o envio/publicação fica no app de destino. Cancelar não executa a ação.
Apps financeiros são recusados na ação de abertura. App ausente e permissão
negada retornam erro à IA. O compartilhamento abre o seletor do Android.

Agenda solicita READ_CALENDAR/WRITE_CALENDAR ao usar a ação, conforme necessário.
SET_ALARM é uma permissão normal concedida pelo Android na instalação, sem
diálogo de runtime; é verificada apenas ao usar alarme/timer. Não se pede acesso
especial a alarmes exatos. Datas aceitam ISO local, “amanhã às 15h”, “hoje às
15:30” e “segunda que vem” (próxima ocorrência estritamente futura, 9h se não
houver horário). O fuso é o do aparelho.

Lembretes ficam em armazenamento privado persistente, com fila de envio e cópia
dos lembretes do PC. Com o app aberto e PC pareado disponível, GET/POST
`/lembretes` sincronizam a cada dez segundos. IDs tornam reenvios idempotentes;
a marca `feito` do PC é preservada. O PC continua responsável pelas notificações
T5; não há agendador de notificações Android em segundo plano. A ferramenta
`listar_lembretes` inclui pendentes locais e a última cópia do PC. O roteamento
da C2 permanece: PC disponível recebe o pedido; as ferramentas locais são usadas
pelo caminho da nuvem.

## Acessibilidade (C4)

Em **Config. → Ativar Acessibilidade**, procure **Apps instalados → Secretário —
operar apps** e habilite o serviço. Android 13+: se a opção estiver bloqueada após
instalar o APK, abra **Configurações → Apps → Secretário → Informações do app →
menu ⋮ → Permitir configurações restritas**, autentique-se e volte à Acessibilidade.
Os nomes dos menus variam conforme o fabricante.

A operação de tela exige **Android 14+**, embora as outras funções continuem no
Android 10+. A Acessibilidade não fornece os flags da janela de outro app.
Por isso, antes de solicitar a raiz e novamente antes de executar uma ação, o
serviço usa `takeScreenshotOfWindow` (API 34) como verificação de janela segura.
`FLAG_SECURE`, falha da captura, origem desconhecida ou mudança de janela
interrompem a sessão. O buffer é fechado sem ler pixels, criar bitmap, persistir
ou enviar imagem. Em versões anteriores, a operação falha antes de acessar nós.
Referência: [AccessibilityService — captura por janela e SECURE_WINDOW](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService#takeScreenshotOfWindow(int,java.util.concurrent.Executor,android.accessibilityservice.AccessibilityService.TakeScreenshotCallback)).

Na nuvem, a ferramenta `operar_tela` aceita `iniciar`, `ler`, `tocar`, `preencher`,
`rolar`, `voltar`, `gesto` e `parar`. Abra primeiro o app desejado (por exemplo com
`abrir_app`). O usuário confirma a sessão no overlay; a IA lê índices compactos
e atua um passo por vez, até 15 passos/chamadas por pedido. Após uma mutação deve
ler novamente; índices são invalidados por mudanças de conteúdo. Gestos são
somente toques dentro de um nó clicável sem filhos, não coordenadas livres.
Todas as mutações pedem confirmação humana individual no overlay, incluindo
publicar, enviar, comprar, apagar, aceitar e botões sem rótulo. Recusa, timeout de
60 segundos e **Parar** encerram a sessão. Não há retomada automática.

Um toque do usuário fora do painel pausa a automação imediatamente. O controlador
de interação recebe o início e delega o toque original ao app. O painel é uma
`TYPE_ACCESSIBILITY_OVERLAY`, com **Parar** sempre disponível durante a sessão;
não requer permissão de sobreposição comum. A configuração pede somente eventos
de janela/conteúdo, IDs, janelas interativas, árvore, gesto, captura para segurança
e controle de interação para detectar o toque. Não habilita exploração por gestos
para operar a interface: os toques são delegados normalmente.

Eventos financeiros são descartados após consultar somente o pacote de origem,
sem ler texto, descrição ou source. Cada nó é filtrado por pacote e `isPassword`
antes de texto, IDs ou filhos; campos de senha nunca são lidos/preenchidos.
Telas com senha ou indícios de login, CAPTCHA e códigos interrompem a sessão.
Nenhum conteúdo dessas telas é retornado à IA. A árvore é limitada a 150 nós e
30 níveis. Não há leitura automática de eventos, imagens nem notificações.

**Config. → Pacote para bloquear → Acrescentar bloqueio** adiciona um pacote à
lista privada persistida, sem opção de remoção. Isso também vale para `abrir_app`.
A IA não recebe ferramenta para editar essa lista. A política é Kotlin pura em
`BloqueioFinanceiro.kt`: lista fixa imutável, adicionais somente cumulativos,
heurística por segmentos e prefixos/sufixos financeiros. `pay` usa segmento ou
sufixo com exceções para palavras comuns (display, cosplay, screenplay, replay,
roleplay, airplay, fairplay, gameplay); nomes genéricos como neon, next, original e
rico não são bloqueados isoladamente. Spotify e WhatsApp ficam permitidos. A
heurística não é um catálogo completo de todos os apps financeiros existentes;
acrescente apps desconhecidos antes de usá-los. Não há exceção que libere fixos.

Lista fixa (também bloqueia subpacotes; comparação sem distinção de caixa):

```
com.itau, com.itau.personnalite, com.itau.iti, com.bradesco, com.bradesco.next,
br.com.bradesco, com.bradesco.netempresa, br.com.bb.android, br.com.bb.bbmobi,
br.com.caixa, br.com.gabba.caixa, br.gov.caixa.tem, com.santander.app,
com.santander.app.empresarial, com.nu.production, br.com.intermedium,
com.c6bank.app, com.picpay, com.mercadopago.wallet, br.com.uol.ps.myaccount,
br.com.uol.pagseguro, br.com.neon, com.next.banco, br.com.original.bank,
com.btg.pactual.banking, com.btg.pactual.digital, br.com.xp.carteira,
br.com.xpinc.mobile, br.com.rico.mobile, br.com.sicoobnet, br.com.sicredimobi,
br.com.banrisul, com.binance.dev, com.coinbase.android, org.toshi,
com.wallet.crypto.trustapp, io.metamask, exodusmovement.exodus, app.phantom,
com.crypto.acct, piuk.blockchain.android, com.paypal.android.p2pmobile,
com.google.android.apps.walletnfcrel, com.samsung.android.spay,
com.revolut.revolut, com.transferwise.android
```

Os testes JVM do bloqueio cobrem todos os fixos e subpacotes, caixa/locale,
heurística, falsos positivos, origem desconhecida, fronteiras de pacote,
validação e cópia da lista adicional, imutabilidade dos fixos e adições cumulativas.
O revisor executa `./gradlew testDebugUnitTest assembleDebug`. O Codex não rodou
Gradle nem fez commit. Verificações isoladas não substituem testes em aparelho:
validar toque, overlay, tela com senha, app bloqueado, janela FLAG_SECURE,
confirmação recusada e invalidação de índices antes de uso real.

## Gastos (C5)

A tela Gastos recebe os rascunhos ditados/digitados na conversa, permite corrigir
e confirmar, importar CSV com colunas mapeadas, ler comprovantes com CameraX e
ML Kit Text Recognition empacotado, corrigir categorias e definir orçamentos
mensais (aviso a partir de 80%). A consulta “quanto gastei esse mês com mercado?”
usa somente os gastos confirmados. Todas as contas e o protocolo usam centavos
inteiros; os campos em reais são texto convertido sem ponto flutuante.

O OCR roda no aparelho; seu texto é enviado transitoriamente à IA configurada
para extrair valor, data, loja e categoria. Foto e texto não entram no histórico
nem no banco. Sem chave de IA, voz/texto permitem categoria manual; foto exige a
chave. Categorias corrigidas são lembradas por estabelecimento.

Notificações começam desligadas, sem apps marcados. Para usar, ligue a chave em
Gastos, conceda acesso na tela do Android e marque os bancos desejados. Somente
os apps marcados e reconhecidos por BloqueioFinanceiro são considerados. O
serviço filtra compras aprovadas/Pix enviado e persiste apenas campos extraídos,
pendentes de confirmação. Não abre apps nem altera o bloqueio de intents ou
Acessibilidade. Reentregas da mesma notificação usam identidade determinística;
CSV ignora repetição por data, valor, estabelecimento e origem.

Room passa de 1 para 2 com MIGRACAO_1_2 (somente CREATE TABLE gastos). Não há
fallback destrutivo. O schema 1 exportado foi preservado; o KSP exportará o schema
2 em app/schemas na próxima compilação do revisor. Validar a atualização de uma
instalação v1 com mensagens/fatos existentes e conferir sua preservação.

A sincronização ocorre enquanto o app está aberto. POST /gastos recebe
`{"gastos": [...]}` (até 50); cada item tem id local, data ISO, valor_centavos,
descricao curta, estabelecimento, categoria, forma, origem e confirmado.
Responde `{"ids": [...]}`. GET /gastos?desde=AAAA-MM-DD devolve
`{"gastos": [...]}` do aparelho autenticado. Reenvio/correção faz upsert pela
chave (aparelho autenticado, id local), sem confiar em aparelho enviado no corpo.
Correções locais aguardam confirmação do PC antes de sair da fila.

No PC, voz/gastos.py usa registro.BANCO, incluído no backup integral existente.
Ao receber um lote gera Finanças/Gastos AAAA-MM.md no cofre, somente com totais
confirmados por categoria (sem detalhes de cartão/conta). Aceita banco/cofre
temporários nos testes. Se a gravação da nota falhar após salvar o banco, o
celular mantém o lote pendente e pode reenviá-lo sem duplicação.

Para o revisor: executar os testes Python de gastos/ponte e os testes JVM,
compilar e validar em aparelho câmera, permissão de notificações, seleção de
apps, recusa de confirmação, migração v1→v2, sincronização offline/reenvio,
CSV com vírgula decimal, correção de categoria e aviso de orçamento.
Gradle e pytest não foram executados pelo Codex.

### C6 — Postagens

Peça “Cria uma postagem sobre Kotlin para o LinkedIn” (ou Instagram). O PC
gera o rascunho pela fila existente; sem PC, a nuvem gera sem ferramentas de
ação. O resumo de Perfil/ e Preferências/ vem de GET /memoria/perfil-estilo,
autenticado, limitado a 1600 caracteres e filtrado no PC. O último resumo
fica nas preferências criptografadas do celular para uso sem PC.

Edite o rascunho (até 2000 caracteres, limite atual da Acessibilidade), escolha
uma imagem na galeria e confira a prévia. “Aprovar e abrir no app” compartilha
pela C3. Escolha a rede indicada no seletor em até 60 segundos. A C4 preenche
o campo e procura Avançar/Seguinte/Publicar, confirmando as ações no overlay.
No botão final pergunta exatamente “Posso publicar?”: somente “Sim” permite
o clique. Parar, recusar, tempo esgotado ou mudança de tela interrompem o fluxo.
Exige Android 14+ e Acessibilidade habilitada, como a C4.

Depois do clique, volte ao Secretário e confirme se a postagem apareceu na
rede. Só então um recibo persistente entra na fila para POST /postagens
(`id`, `rede`, `texto`). O PC acrescenta uma linha em Histórico/Postagens.md;
reenvios do mesmo id não duplicam a linha. A sincronização ocorre com o app
aberto. A imagem não é enviada ao cofre. Telas sem os controles reconhecidos
interrompem a preparação; não há tentativa de adivinhar coordenadas.

Revisor: executar voz/tests/test_postagens.py, os testes existentes de
memória/ponte e PostagensTest (JVM). Validar no aparelho edição, prévia da
galeria, PC ausente com cache, recusa/Parar antes de publicar, mudança de
tela, publicação confirmada e reenvio do histórico sem duplicação.

### C7 — Crescer com o uso

Room v3 adiciona somente `aprendizados` pela migração 2→3; mensagens, fatos e
gastos permanecem intactos. A cadeia 1→2→3 continua registrada, sem fallback
destrutivo. O schema 2 exportado permanece preservado; o KSP exporta o 3 na
compilação do revisor.

Na Acessibilidade, `iniciar` recebe uma intenção do catálogo (mensagem, postagem,
pesquisa ou outro). `concluir` só deve ser chamado depois do sucesso: pergunta ao
usuário se tudo terminou e se pode guardar. Parar, recusar, erro, gestos ou alvo
sem seletor seguro não geram receita. Só persistem app, intenção e ações com
seletores por id ou texto estático; campos editáveis exigem id. Valores digitados
nunca são serializados, inclusive quando reaparecem em rótulos selecionados.

`reutilizar` recebe textos novos do pedido atual, um por preenchimento, e valida
seletor único a cada tela. Mudança ou ambiguidade interrompe e invalida a receita;
a IA deve continuar da tela atual e reaprender, sem repetir ações anteriores.
Todas as mutações passam pela confirmação existente, inclusive ações finais.
Postagens também aprendem e reutilizam; a gravação aguarda a confirmação de que
a publicação apareceu. BloqueioFinanceiro continua obrigatório em cada etapa.

O primeiro padrão de rotina suportado é a leitura da agenda: leituras locais
bem-sucedidas na nuvem e pedidos de agenda aceitos na fila do PC alimentam o
histórico de uso, por dia da semana/hora.
Exige três ocorrências em três semanas distintas. Uma sugestão é mostrada por
vez; aceitar agenda uma leitura semanal com WorkManager, após permissões de
agenda/notificações. Recusa fica registrada para não insistir. O Android pode
adiar a execução por economia de bateria. A agenda aparece na conversa com uma
notificação que abre o app, sem automação de ações finais.

Quando falta uma capacidade, a nuvem chama `pedido_nao_atendido`: o pedido fica
numa fila persistente e segue por POST /bugs com tipo `melhoria` quando o PC
reconecta. O PC deduplica melhorias repetidas. Cancelamentos e bloqueios de
segurança não devem gerar melhorias. /bugs mantém `bug` como tipo padrão e
rejeita tipos desconhecidos.

Revisor: executar CrescimentoTest e os testes Python de ponte/diagnóstico;
compilar; atualizar instalação com schema 2 contendo mensagens/fatos/gastos e
conferir preservação. No aparelho, verificar receita com texto diferente,
seletor alterado/duplicado, app bloqueado, recusa da ação final e da gravação,
sugestão recusada/aceita e fila de melhorias offline. Gradle e pytest não foram
executados pelo Codex.
