# Secretário Android — C2/C3

Base pessoal em Kotlin/Compose, tema escuro/menta, Android 10 ou superior.
`RegistroAcoes` expõe as ações C3 à nuvem por chamadas de função.
Não há Acessibilidade.

## Compilar e instalar (revisor)

Pré-requisitos: JDK 17, Android SDK com `platforms;android-35`, build-tools e
platform-tools; `ANDROID_HOME` apontando para o SDK (ou `sdk.dir` em
`local.properties`). Aceite as licenças com `sdkmanager --licenses`.

O `gradle-wrapper.jar` será gerado pelo revisor. Os scripts e as propriedades
estão incluídos, com distribuição oficial Gradle 8.9. Para gerar o JAR com uma
instalação confiável do Gradle 8.9, dentro de `celular/`:

```powershell
gradle wrapper --gradle-version 8.9 --distribution-type bin
.\gradlew.bat testDebugUnitTest assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

Em Linux/macOS: `chmod +x gradlew`, `./gradlew testDebugUnitTest assembleDebug` e
`adb install -r app/build/outputs/apk/debug/app-debug.apk`.
O APK debug usa a assinatura local de desenvolvimento. Para instalar manualmente,
copie o APK e habilite a instalação de fontes desconhecidas para o app que o abrir.
Nenhum comando Gradle foi executado durante a implementação.

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
