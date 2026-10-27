package com.deivid.secretario

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.accessibilityservice.GestureDescription
import android.accessibilityservice.TouchInteractionController
import android.view.Display
import android.view.MotionEvent
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.coroutines.resume

class ServicoAcessibilidade : AccessibilityService() {
    private val trava = Mutex()
    private var pacote: String? = null
    private var janela = -1
    private var revisao = 0L
    private var pausado = true
    private var passos = 0
    private var leitura = -1L
    private var assinatura = emptyList<String>()
    private var controlador: TouchInteractionController? = null
    private var senhaEncontrada = false
    private var sobreposicao: LinearLayout? = null
    private var resposta: CompletableDeferred<Boolean>? = null
    private var politica = BloqueioFinanceiro()
    private val banco by lazy { Banco.abrir(this) }
    private var gravador: GravadorReceita? = null
    private var postagemConcluida: GravadorReceita? = null
    private var appReceita: String? = null
    private var telaReceita = emptyList<ElementoReceita>()
    private val preferencias by lazy { getSharedPreferences("bloqueio_acessibilidade", MODE_PRIVATE) }

    companion object { var atual: ServicoAcessibilidade? = null; private set }

    override fun onServiceConnected() {
        politica = BloqueioFinanceiro(preferencias.getStringSet("adicionais", emptySet()).orEmpty())
        atual = this
        if (Build.VERSION.SDK_INT >= 34) {
            serviceInfo = serviceInfo.apply {
                flags = flags or AccessibilityServiceInfo.FLAG_REQUEST_TOUCH_EXPLORATION_MODE
            }
            controlador = getTouchInteractionController(Display.DEFAULT_DISPLAY).also { controle ->
                controle.registerCallback(mainExecutor, object : TouchInteractionController.Callback {
                    override fun onMotionEvent(evento: MotionEvent) {
                        if (evento.actionMasked == MotionEvent.ACTION_DOWN) {
                            val noPainel = sobreposicao?.let { painel ->
                                val posicao = IntArray(2)
                                painel.getLocationOnScreen(posicao)
                                Rect(posicao[0], posicao[1], posicao[0] + painel.width,
                                    posicao[1] + painel.height).contains(evento.rawX.toInt(), evento.rawY.toInt())
                            } == true
                            if (!noPainel) parar()
                            controle.requestDelegating()
                        }
                    }
                    override fun onStateChanged(estado: Int) = Unit
                })
            }
        }
    }
    override fun onAccessibilityEvent(evento: AccessibilityEvent?) {
        if (evento == null) return
        // Só metadados de origem; nunca consultar text, source, description ou nós do evento.
        val origem = evento.packageName?.toString()
        if (politica.bloqueado(origem)) { parar(); pacote = null; janela = -1; revisao++; return }
        if (evento.eventType == AccessibilityEvent.TYPE_TOUCH_INTERACTION_START) return
        if (origem == packageName) return // O overlay não substitui a janela alvo.
        pacote = origem
        janela = evento.windowId
        revisao++
    }
    override fun onInterrupt() = parar()
    override fun onDestroy() {
        parar()
        if (Build.VERSION.SDK_INT >= 34) controlador?.unregisterAllCallbacks()
        banco.close()
        atual = null; super.onDestroy()
    }
    private fun parar() {
        gravador = null; appReceita = null; telaReceita = emptyList()
        pausado = true
        leitura = -1L
        assinatura = emptyList()
        resposta?.complete(false)
        resposta = null
        sobreposicao?.let { runCatching { getSystemService(WindowManager::class.java).removeView(it) } }
        sobreposicao = null
    }
    private fun painel(texto: String, confirmar: Boolean = false) {
        sobreposicao?.let { getSystemService(WindowManager::class.java).removeView(it) }
        val vista = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(0xff243831.toInt())
            addView(TextView(this@ServicoAcessibilidade).apply { this.text = texto; setTextColor(-1) })
            if (confirmar) addView(Button(this@ServicoAcessibilidade).apply {
                this.text = if (texto == "Posso publicar?") "Sim" else "Confirmar esta ação"
                setOnClickListener { resposta?.complete(true) }
            })
            addView(Button(this@ServicoAcessibilidade).apply {
                this.text = "Parar"; setOnClickListener { parar() }
            })
        }
        getSystemService(WindowManager::class.java).addView(vista, WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, android.graphics.PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.END })
        sobreposicao = vista
    }
    private suspend fun confirmar(texto: String): Boolean {
        val espera = CompletableDeferred<Boolean>()
        resposta = espera
        painel(texto, true)
        return try { withTimeoutOrNull(60000) { espera.await() } == true }
        finally { resposta = null; if (!pausado) painel("Automação ativa ($passos/15)") }
    }
    private suspend fun janelaPermitida(): android.view.accessibility.AccessibilityWindowInfo {
        check(!pausado && !politica.bloqueado(pacote)) { "Automação pausada ou app bloqueado" }
        // A API pública que informa SECURE_WINDOW é por janela, a partir do Android 14.
        // Versões anteriores falham fechadas: nenhum nó é solicitado.
        check(Build.VERSION.SDK_INT >= 34) { "Operar tela exige Android 14+ para verificar FLAG_SECURE" }
        val versao = revisao
        val alvo = windows.firstOrNull { it.isActive && it.id == janela }
            ?: error("Janela mudou; leia a tela novamente")
        val permitido = withTimeout(5000) { suspendCancellableCoroutine<Boolean> { continuacao ->
            takeScreenshotOfWindow(alvo.id, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(resultado: ScreenshotResult) {
                    // Descartar buffer sem converter, ler pixels, persistir ou enviar à IA.
                    resultado.hardwareBuffer.close()
                    if (continuacao.isActive) continuacao.resume(true)
                }
                override fun onFailure(erro: Int) {
                    parar() // Inclui ERROR_TAKE_SCREENSHOT_SECURE_WINDOW e qualquer falha.
                    if (continuacao.isActive) continuacao.resume(false)
                }
            })
        } }
        check(permitido && !pausado && versao == revisao && !politica.bloqueado(pacote)) {
            "Janela segura, alterada ou verificação indisponível; interrompido"
        }
        return alvo
    }
    private fun permitido(no: AccessibilityNodeInfo): Boolean {
        // Ordem obrigatória: pacote e senha antes de qualquer conteúdo ou filhos.
        if (politica.bloqueado(no.packageName?.toString())) return false
        if (no.isPassword) { senhaEncontrada = true; return false }
        return no.packageName?.toString() == pacote
    }
    private fun arvore(raiz: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        senhaEncontrada = false
        val nos = mutableListOf<AccessibilityNodeInfo>()
        var visitados = 0
        var incompleta = false
        fun visitar(no: AccessibilityNodeInfo, nivel: Int) {
            if (++visitados > 150 || nivel > 30) { incompleta = true; return }
            if (!permitido(no)) return
            if (!no.isVisibleToUser) return
            nos.add(no)
            for (i in 0 until no.childCount) {
                if (visitados >= 150) { incompleta = true; break }
                no.getChild(i)?.let { visitar(it, nivel + 1) }
            }
        }
        visitar(raiz, 0)
        check(!incompleta) { "Árvore excede limite seguro; sessão interrompida" }
        return nos
    }
    private fun resumo(no: AccessibilityNodeInfo) =
        "id=${no.viewIdResourceName.orEmpty().take(120)} texto=${no.text?.toString().orEmpty().take(250)} descrição=${no.contentDescription?.toString().orEmpty().take(150)} clicável=${no.isClickable} editável=${no.isEditable}"

    suspend fun executar(acao: String, indice: Int?, texto: String, x: Float?, y: Float?, publicacao: Boolean = false, intencao: String = ""): String =
        withContext(Dispatchers.Main.immediate) { trava.withLock {
            if (acao == "concluir") {
                check(!pausado && pacote == appReceita && !politica.bloqueado(pacote)) { "Sessão inválida" }
                janelaPermitida()
                val candidato = gravador
                val confirmado = confirmar("A sequência terminou com sucesso? Posso guardar os passos para a próxima vez?")
                if (confirmado && !pausado) janelaPermitida()
                val receita = if (!pausado && pacote == appReceita) candidato?.concluir(true, confirmado) else null
                try {
                    if (receita != null) banco.aprendizados().guardar(AprendizadoLocal("receita:${receita.app}:${receita.intencao}", receita.json()))
                } finally { parar() }
                return@withLock if (receita != null) "Receita guardada sem valores de campos." else "Receita não guardada."
            }
            if (acao == "parar") { parar(); return@withLock "Automação parada." }
            if (acao == "iniciar") {
                check(pausado) { "Sessão já ativa" }
                check(Build.VERSION.SDK_INT >= 34) { "Operar tela exige Android 14+" }
                check(!politica.bloqueado(pacote)) { "App bloqueado ou sem janela conhecida" }
                passos = 0; pausado = false
                if (!confirmar("Permitir sessão de até 15 passos neste app?")) {
                    parar(); return@withLock "Sessão recusada ou pausada pelo toque."
                }
                appReceita = pacote
                gravador = GravadorReceita(pacote.orEmpty(), intencao, politica)
            }
            check(!pausado) { "Pausado. Peça uma nova sessão ao usuário." }
            check(passos < 15) { parar(); "Limite de 15 passos atingido" }
            passos++
            try {
                val alvo = janelaPermitida()
                val raiz = alvo.root ?: error("Sem árvore acessível")
                val nos = arvore(raiz)
                check(!senhaEncontrada) { "Tela com campo de senha: automação recusada" }
                check(nos.isNotEmpty()) { "Árvore bloqueada ou vazia" }
                check(pacote == appReceita) { "App mudou durante a sequência" }
                gravador?.protegerValores(nos.filter { it.isEditable }.map { it.text?.toString().orEmpty() })
                // Não automatizar autenticação, CAPTCHA, códigos nem seus controles adjacentes.
                check(nos.none { Regex("senha|password|login|log.?in|entrar|captcha|código|codigo|otp|autentica", RegexOption.IGNORE_CASE)
                    .containsMatchIn(resumo(it)) }) { "Tela de autenticação/código: operação recusada" }
                if (acao in listOf("iniciar", "ler")) {
                    leitura = revisao
                    assinatura = nos.map(::resumo)
                    telaReceita = nos.map { ElementoReceita(it.viewIdResourceName.orEmpty(),
                        if (it.isEditable) "" else it.text?.toString().orEmpty(), it.isEditable) }
                    val tela = assinatura.mapIndexed { i, linha -> "$i $linha" }.joinToString("\n")
                    if (passos == 15) parar()
                    return@withLock tela
                }
                check(leitura == revisao && assinatura == nos.map(::resumo)) { "Índices expirados; leia novamente" }
                require(acao in listOf("tocar", "preencher", "rolar", "voltar", "gesto"))
                val no = if (acao in listOf("tocar", "preencher", "rolar", "gesto"))
                    nos.getOrNull(indice ?: -1) ?: error("Índice inválido; leia a tela") else null
                val versao = revisao
                val descricao = no?.let(::resumo).orEmpty()
                val elemento = no?.let { ElementoReceita(it.viewIdResourceName.orEmpty(),
                    if (it.isEditable) "" else it.text?.toString().orEmpty(), it.isEditable) }
                // Confirma toda mutação: cobre publicar/enviar/comprar/apagar/aceitar inclusive ícones.
                val confirmacao = ConfirmacaoPostagem()
                val autorizado = if (publicacao || (acao in listOf("tocar", "gesto") &&
                    Regex("publicar|compartilhar|\\bpost\\b|\\bshare\\b", RegexOption.IGNORE_CASE).containsMatchIn(descricao))) {
                    confirmacao.aguardar { pergunta -> if (confirmar(pergunta)) "sim" else "não" }
                } else confirmar("$acao: $descricao\n${texto.take(500)}\nAutorizar apenas esta ação?")
                if (!autorizado) {
                    parar(); return@withLock "Ação cancelada ou pausada."
                }
                check(versao == revisao && janelaPermitida().id == alvo.id) { "Tela mudou durante confirmação" }
                if (no != null) check(permitido(no) && no.refresh() && permitido(no) && resumo(no) == descricao) { "Alvo mudou" }
                leitura = -1L
                val sucesso = when (acao) {
                    "tocar" -> no!!.isClickable && no.performAction(AccessibilityNodeInfo.ACTION_CLICK)
                    "preencher" -> {
                        require(texto.length <= 2000)
                        no!!.isEditable && no.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,
                            Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, texto) })
                    }
                    "rolar" -> no!!.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD)
                    "voltar" -> performGlobalAction(GLOBAL_ACTION_BACK)
                    else -> {
                        // Gesto restrito ao retângulo de um nó validado; nunca coordenadas arbitrárias.
                        require(x != null && y != null && x.isFinite() && y.isFinite())
                        val retangulo = Rect().also { no!!.getBoundsInScreen(it) }
                        require(retangulo.contains(x.toInt(), y.toInt()) && no!!.isClickable && no.childCount == 0)
                        val caminho = Path().apply { moveTo(x, y) }
                        suspendCancellableCoroutine<Boolean> { c ->
                            val aceito = dispatchGesture(GestureDescription.Builder().addStroke(
                                GestureDescription.StrokeDescription(caminho, 0, 100)).build(),
                                object : GestureResultCallback() {
                                    override fun onCompleted(g: GestureDescription) { if (c.isActive) c.resume(true) }
                                    override fun onCancelled(g: GestureDescription) { if (c.isActive) c.resume(false) }
                                }, null)
                            if (!aceito && c.isActive) c.resume(false)
                        }
                    }
                }
                gravador?.registrar(acao, elemento, texto, sucesso)
                if (passos == 15) parar()
                "${if (sucesso) "Ação executada" else "Ação recusada pelo app"}; leia a tela antes do próximo passo."
            } catch (e: Exception) { parar(); throw e }
        } }

    suspend fun reutilizar(intencao: String, textos: List<String>, concluir: Boolean = true): String = withContext(Dispatchers.Main.immediate) {
        require(intencao in GravadorReceita.INTENCOES)
        check(!politica.bloqueado(pacote)) { "App bloqueado" }
        val app = pacote ?: error("App desconhecido")
        val chave = "receita:$app:$intencao"
        val receita = banco.aprendizados().ler(chave)?.let(Receita::ler)
            ?: return@withContext "Sem receita. Faça a sequência com a IA e conclua após o sucesso."
        require(receita.app == app && receita.intencao == intencao)
        require(textos.size == receita.passos.count { it.acao == "preencher" }) { "Forneça os textos deste pedido, um por preenchimento" }
        try {
            executar("iniciar", null, "", null, null, intencao = intencao)
            var preenchimento = 0
            for ((i, passo) in receita.passos.withIndex()) {
                check(pacote == app && !politica.bloqueado(app)) { "App mudou ou foi bloqueado" }
                if (i > 0) executar("ler", null, "", null, null)
                val indice = passo.seletor.localizar(telaReceita) ?: error("Seletor mudou ou é ambíguo; a IA precisa refazer a partir desta tela")
                val valor = if (passo.acao == "preencher") textos[preenchimento++] else ""
                check(executar(passo.acao, indice, valor, null, null).startsWith("Ação executada")) { "Receita interrompida" }
            }
            if (concluir) executar("concluir", null, "", null, null)
            else {
                postagemConcluida = gravador
                parar()
                "Sequência executada; aguarde confirmação da publicação."
            }
        } catch (e: Exception) {
            // A próxima execução aprende novamente; nenhuma repetição automática após ação parcial.
            parar()
            if (e is CancellationException) throw e
            banco.aprendizados().apagar(chave)
            throw e
        }
    }

    suspend fun publicarPostagem(item: RascunhoPostagem): Boolean {
        postagemConcluida = null
        val esperado = if (item.rede == "LinkedIn") "com.linkedin.android" else "com.instagram.android"
        withTimeout(60000) {
            while (pacote != esperado || windows.none { it.isActive && it.id == janela }) delay(250)
        }
        check(!politica.bloqueado(esperado)) { "App bloqueado" }
        val salva = banco.aprendizados().ler("receita:$esperado:postagem")?.let(Receita::ler)
        if (salva != null) {
            try {
                return reutilizar("postagem", List(salva.passos.count { it.acao == "preencher" }) { item.texto }, concluir = false)
                    .startsWith("Sequência executada")
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                // Não repetir uma ação parcial: o usuário revisa e a IA pode refazer da tela atual.
                throw IllegalStateException("Receita mudou ou foi interrompida; revise a tela e peça à IA para continuar", e)
            }
        }
        try {
            var tela = executar("iniciar", null, "", null, null, intencao = "postagem")
            var preenchido = false
            repeat(4) {
                check(pacote == esperado) { "O app mudou; publicação interrompida" }
                fun indice(linha: String) = linha.substringBefore(' ').toInt()
                val linhas = tela.lines()
                val campo = linhas.firstOrNull { it.contains("editável=true") }
                if (!preenchido && campo != null) {
                    check(executar("preencher", indice(campo), item.texto, null, null).startsWith("Ação executada"))
                    preenchido = true
                    tela = executar("ler", null, "", null, null)
                } else {
                    val publicar = linhas.firstOrNull { it.contains("clicável=true") &&
                        Regex("(?:texto|descrição)=(?:Publicar|Compartilhar|Post|Share)(?= descrição=| clicável=|$)", RegexOption.IGNORE_CASE).containsMatchIn(it) }
                    if (publicar != null) {
                        // O texto pode ter vindo preenchido pelo intent; o usuário revisa na tela alvo.
                        val sucesso = executar("tocar", indice(publicar), "", null, null, publicacao = true).startsWith("Ação executada")
                        if (sucesso) postagemConcluida = gravador
                        return sucesso
                    }
                    val proximo = linhas.firstOrNull { it.contains("clicável=true") &&
                        Regex("texto=(Avançar|Seguinte|Next)(?= descrição=)", RegexOption.IGNORE_CASE).containsMatchIn(it) }
                        ?: error("Não encontrei Publicar; revise a tela do app")
                    check(executar("tocar", indice(proximo), "", null, null).startsWith("Ação executada"))
                    tela = executar("ler", null, "", null, null)
                }
            }
            error("Limite de preparação atingido")
        } finally { executar("parar", null, "", null, null) }
    }

    suspend fun confirmarReceitaPostagem(confirmado: Boolean) {
        val candidato = postagemConcluida
        postagemConcluida = null
        val receita = candidato?.concluir(true, confirmado) ?: return
        banco.aprendizados().guardar(AprendizadoLocal("receita:${receita.app}:${receita.intencao}", receita.json()))
    }

    fun acrescentarBloqueio(pacote: String) {
        politica.acrescentar(pacote)
        preferencias.edit().putStringSet("adicionais", politica.listaUsuario()).apply()
        parar()
    }
}
