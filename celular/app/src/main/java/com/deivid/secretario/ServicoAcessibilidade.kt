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
        atual = null; super.onDestroy()
    }
    private fun parar() {
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

    suspend fun executar(acao: String, indice: Int?, texto: String, x: Float?, y: Float?, publicacao: Boolean = false): String =
        withContext(Dispatchers.Main.immediate) { trava.withLock {
            if (acao == "parar") { parar(); return@withLock "Automação parada." }
            if (acao == "iniciar") {
                check(pausado) { "Sessão já ativa" }
                check(Build.VERSION.SDK_INT >= 34) { "Operar tela exige Android 14+" }
                check(!politica.bloqueado(pacote)) { "App bloqueado ou sem janela conhecida" }
                passos = 0; pausado = false
                if (!confirmar("Permitir sessão de até 15 passos neste app?")) {
                    parar(); return@withLock "Sessão recusada ou pausada pelo toque."
                }
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
                // Não automatizar autenticação, CAPTCHA, códigos nem seus controles adjacentes.
                check(nos.none { Regex("senha|password|login|log.?in|entrar|captcha|código|codigo|otp|autentica", RegexOption.IGNORE_CASE)
                    .containsMatchIn(resumo(it)) }) { "Tela de autenticação/código: operação recusada" }
                if (acao in listOf("iniciar", "ler")) {
                    leitura = revisao
                    assinatura = nos.map(::resumo)
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
                if (passos == 15) parar()
                "${if (sucesso) "Ação executada" else "Ação recusada pelo app"}; leia a tela antes do próximo passo."
            } catch (e: Exception) { parar(); throw e }
        } }

    suspend fun publicarPostagem(item: RascunhoPostagem): Boolean {
        val esperado = if (item.rede == "LinkedIn") "com.linkedin.android" else "com.instagram.android"
        withTimeout(60000) {
            while (pacote != esperado || windows.none { it.isActive && it.id == janela }) delay(250)
        }
        try {
            var tela = executar("iniciar", null, "", null, null)
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
                        return executar("tocar", indice(publicar), "", null, null, publicacao = true).startsWith("Ação executada")
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

    fun acrescentarBloqueio(pacote: String) {
        politica.acrescentar(pacote)
        preferencias.edit().putStringSet("adicionais", politica.listaUsuario()).apply()
        parar()
    }
}
