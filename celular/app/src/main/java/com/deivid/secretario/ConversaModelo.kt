package com.deivid.secretario

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*

class ConversaModelo(aplicacao: Application) : AndroidViewModel(aplicacao) {
    val configuracao = Configuracao(aplicacao)
    private val banco = Banco.abrir(aplicacao)
    private val dados = banco.dados()
    val mensagens = dados.mensagens().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val fatos = dados.quantidadeFatos().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0)
    val fila = MutableStateFlow<List<TarefaPc>>(emptyList())
    val estado = MutableStateFlow("pronto")
    val cerebro = MutableStateFlow("Nuvem")
    val conectado = MutableStateFlow(false)
    val enviando = MutableStateFlow(false)
    val aviso = MutableStateFlow<String?>(null)
    val falar = MutableSharedFlow<String>(extraBufferCapacity = 16)
    val interfaceAcoes = InterfaceAcoes()
    val preferenciasGastos = PreferenciasGastos(aplicacao)
    private val gastos = GastosCelular(banco.gastos(), preferenciasGastos)
    val listaGastos = banco.gastos().observar().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val rascunhoGasto = MutableStateFlow<RascunhoGasto?>(null)
    val resumoGastos = MutableStateFlow("")
    val postagem = MutableStateFlow<RascunhoPostagem?>(null)
    private var tarefasPostagem = emptyList<Long>()
    private val respostasPostagem = mutableMapOf<Long, String>()
    private var esperandoPostagem = false
    private var compartilhada: RascunhoPostagem? = null
    private val iaGastos = ClienteNuvem(configuracao::nuvem, RegistroAcoes(emptyList()))
    private val lembretes = LembretesCelular(aplicacao)
    private val pc = ClientePc({ evento ->
        viewModelScope.launch {
            when (evento) {
                is EventoPc.Mensagem -> {
                    if (esperandoPostagem && evento.tarefa != null && evento.autor.lowercase() in listOf("secretário", "secretario", "assistente")) {
                        respostasPostagem[evento.tarefa] = evento.texto
                        receberRascunho()
                    }
                    dados.inserir(MensagemLocal(autor = evento.autor, texto = evento.texto, origem = "PC"))
                    if (evento.autor.lowercase() !in listOf("você", "voce", "usuario", "usuário", "deivid", "sistema"))
                        falar.emit(evento.texto)
                }
                is EventoPc.Estado -> estado.value = evento.estado
                is EventoPc.Fila -> fila.value = evento.tarefas
                is EventoPc.Outro -> Unit
            }
        }
    }, { conectado.value = it })
    private val registroAcoes = acoesCelular(AmbienteAcoes(aplicacao, interfaceAcoes::confirmar,
        interfaceAcoes::permitir, interfaceAcoes::abrir, lembretes))
    private val roteador = Roteador(pc, ClienteNuvem(configuracao::nuvem, registroAcoes, dados::recentes))
    private var observacao: Job? = null

    fun iniciar() {
        if (observacao?.isActive == true) return
        observacao = viewModelScope.launch {
            while (isActive) {
                try {
                    val pareamento = configuracao.pareamento()
                    if (pareamento != null && withTimeoutOrNull(1500) { pc.conectar(pareamento) } == true) {
                        configuracao.guardarPerfilEstilo(pc.perfilEstilo())
                        sincronizarPostagens()
                        lembretes.sincronizar(pc)
                        gastos.sincronizar(pc)
                        val pendentes = dados.fatos()
                        if (pendentes.isNotEmpty()) {
                            pc.sincronizar(pendentes.map { it.texto })
                            dados.confirmar(pendentes.map { it.id })
                        }
                    }
                } catch (e: CancellationException) { throw e }
                catch (_: Exception) { /* A fila persiste para a próxima conexão. */ }
                delay(10000)
            }
        }
    }

    fun parar() { observacao?.cancel(); observacao = null; pc.desligar() }

    fun parear(texto: String) {
        runCatching { configuracao.parear(Pareamento.ler(texto)) }
            .onSuccess { parar(); iniciar(); aviso.value = "PC pareado" }
            .onFailure { aviso.value = "QR inválido: ${it.message}" }
    }

    fun esquecerPc() { parar(); configuracao.removerPc(); fila.value = emptyList(); iniciar() }

    fun aprender(texto: String) {
        if (texto.isBlank()) return
        viewModelScope.launch {
            dados.aprender(FatoPendente(texto = texto.trim()))
            aviso.value = "Fato guardado para sincronizar com o PC"
        }
    }

    fun enviar(texto: String) {
        if (enviando.value || texto.isBlank()) return
        Postagens.rede(texto)?.let { prepararPostagem(texto, it); return }
        if (Regex("^(gastei|paguei)\\b", RegexOption.IGNORE_CASE).containsMatchIn(texto.trim())) {
            prepararGasto(texto); return
        }
        if (texto.contains("quanto gastei", true)) {
            viewModelScope.launch {
                val categoria = Regex("com\\s+(.+?)[?.]?$", RegexOption.IGNORE_CASE).find(texto)?.groupValues?.get(1).orEmpty()
                dados.inserir(MensagemLocal(autor = "Secretário", texto = gastos.resumo(categoria), origem = "Celular"))
            }; return
        }
        viewModelScope.launch {
            enviando.value = true
            aviso.value = null
            try {
                dados.inserir(MensagemLocal(autor = "Você", texto = texto.trim(), origem = "Celular"))
                when (val resposta = roteador.enviar(texto, configuracao.pareamento())) {
                    is Resposta.Pc -> { cerebro.value = "PC"; estado.value = "Enfileirado: ${resposta.tarefas.joinToString()}" }
                    is Resposta.Nuvem -> {
                        cerebro.value = "Nuvem"
                        dados.inserir(MensagemLocal(autor = "Secretário", texto = resposta.texto, origem = "Nuvem"))
                        falar.emit(resposta.texto)
                    }
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                aviso.value = "Não foi possível concluir (${e.message}). Se o PC recebeu, confira a fila antes de repetir."
            } finally { enviando.value = false }
        }
    }

    override fun onCleared() { parar(); banco.close() }

    private fun receberRascunho() {
        tarefasPostagem.firstNotNullOfOrNull { respostasPostagem[it] }?.let { texto ->
            postagem.value = postagem.value?.copy(texto = texto.take(2000))
            esperandoPostagem = false; tarefasPostagem = emptyList(); respostasPostagem.clear()
        }
    }

    private fun prepararPostagem(texto: String, rede: String) = viewModelScope.launch {
        enviando.value = true
        esperandoPostagem = true; respostasPostagem.clear(); tarefasPostagem = emptyList()
        postagem.value = RascunhoPostagem(rede)
        compartilhada = null
        try {
            val pareamento = configuracao.pareamento()
            val conectado = pareamento != null && withTimeoutOrNull(1500) {
                try { pc.conectar(pareamento) } catch (e: CancellationException) { throw e } catch (_: Exception) { false }
            } == true
            if (conectado) {
                try { configuracao.guardarPerfilEstilo(pc.perfilEstilo()) }
                catch (e: CancellationException) { throw e } catch (_: Exception) { /* Usa o último resumo. */ }
            }
            val pedido = Postagens.pedido(texto, rede, configuracao.perfilEstilo())
            if (conectado) {
                cerebro.value = "PC"
                tarefasPostagem = pc.enviar(pedido)
                receberRascunho()
            } else {
                cerebro.value = "Nuvem"
                postagem.value = postagem.value?.copy(texto = iaGastos.responder(pedido).take(2000))
                esperandoPostagem = false
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { esperandoPostagem = false; aviso.value = "Rascunho não concluído: ${e.message}" }
        finally { enviando.value = false }
    }

    fun editarPostagem(item: RascunhoPostagem) {
        if (postagem.value?.texto != item.texto) esperandoPostagem = false
        postagem.value = item.copy(texto = item.texto.take(2000))
        compartilhada = null
    }

    fun compartilharPostagem() = viewModelScope.launch {
        val item = postagem.value ?: return@launch
        if (item.texto.isBlank() || enviando.value) return@launch
        enviando.value = true
        var abrirPublicacao = false
        try {
            val ambiente = AmbienteAcoes(getApplication(), interfaceAcoes::confirmar, interfaceAcoes::permitir, interfaceAcoes::abrir, lembretes)
            val resultado = Compartilhar(ambiente).executar(buildJsonObject { put("texto", item.texto); put("imagem", item.imagem) })
            if (!resultado.contains("cancelado", true)) { compartilhada = item; abrirPublicacao = true }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { aviso.value = "Compartilhamento falhou: ${e.message}" }
        finally { enviando.value = false }
        if (abrirPublicacao) publicarPostagem()
    }

    fun publicarPostagem() = viewModelScope.launch {
        val item = postagem.value ?: return@launch
        if (enviando.value) return@launch
        enviando.value = true
        try {
            check(compartilhada == item) { "Aprove e compartilhe este rascunho primeiro" }
            val servico = ServicoAcessibilidade.atual ?: error("Ative a Acessibilidade")
            if (servico.publicarPostagem(item)) {
                // Um clique aceito não prova que o servidor da rede concluiu a publicação.
                if (interfaceAcoes.confirmar("A postagem apareceu publicada no ${item.rede}?")) {
                    val pendentes = Json.parseToJsonElement(configuracao.postagensPendentes()).jsonArray
                    val recibo = buildJsonObject {
                        put("id", java.util.UUID.randomUUID().toString()); put("rede", item.rede); put("texto", item.texto)
                    }
                    configuracao.guardarPostagens(JsonArray(pendentes + recibo).toString())
                    postagem.value = null; compartilhada = null
                    try { sincronizarPostagens() } catch (e: CancellationException) { throw e }
                    catch (_: Exception) { aviso.value = "Publicação guardada; histórico será enviado ao PC" }
                }
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { aviso.value = "Publicação interrompida: ${e.message}" }
        finally { enviando.value = false }
    }

    private suspend fun sincronizarPostagens() {
        val itens = Json.parseToJsonElement(configuracao.postagensPendentes()).jsonArray.toList()
        for (item in itens) {
            pc.registrarPostagem(item)
            val atuais = Json.parseToJsonElement(configuracao.postagensPendentes()).jsonArray
            configuracao.guardarPostagens(JsonArray(atuais.filter { it != item }).toString())
        }
    }

    fun prepararGasto(texto: String, foto: Boolean = false) {
        viewModelScope.launch {
            enviando.value = true
            try {
                val base = if (foto) {
                    val o = iaGastos.extrairGasto(texto, true)
                    val data = o.getValue("data").jsonPrimitive.content
                    java.time.LocalDate.parse(data)
                    val valor = o.getValue("valor_centavos").jsonPrimitive.long
                    require(valor in 1..1_000_000_000_000L)
                    RascunhoGasto(data, valor, ParseGastos.seguro(o.getValue("estabelecimento").jsonPrimitive.content),
                        ParseGastos.seguro(o.getValue("categoria").jsonPrimitive.content), origem = "foto")
                } else ParseGastos.texto(texto) ?: error("Não encontrei o valor em reais")
                val aprendida = preferenciasGastos.categoria(base.estabelecimento)
                val categoria = aprendida ?: if (foto) base.categoria else try {
                    ParseGastos.seguro(iaGastos.extrairGasto(base.estabelecimento, false).getValue("categoria").jsonPrimitive.content)
                } catch (e: CancellationException) { throw e } catch (_: Exception) { "Outros" }
                rascunhoGasto.value = base.copy(categoria = categoria)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { aviso.value = "Não foi possível extrair o gasto: ${e.message}" }
            finally { enviando.value = false }
        }
    }

    fun confirmarGasto(item: RascunhoGasto) = viewModelScope.launch {
        try {
            gastos.guardar(item, true)
            preferenciasGastos.aprender(item.estabelecimento, item.categoria)
            rascunhoGasto.value = null
            atualizarResumo()
        } catch (e: Exception) { aviso.value = "Gasto inválido: ${e.message}" }
    }

    fun corrigirGasto(item: GastoLocal, categoria: String) = viewModelScope.launch {
        gastos.corrigir(item, categoria)
        atualizarResumo()
    }

    fun importarCsv(texto: String, colunas: Map<String, String>) = viewModelScope.launch {
        try {
            val itens = ParseGastos.csv(texto, colunas)
            if (interfaceAcoes.confirmar("Importar ${itens.size} gastos? Total: ${ParseGastos.reais(itens.sumOf { it.valor })}")) {
                var novos = 0
                itens.forEach { if (gastos.guardar(it, true)) novos++ }
                aviso.value = "$novos gastos importados; duplicados ignorados"
                atualizarResumo()
            }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { aviso.value = "CSV inválido: ${e.message}" }
    }

    fun definirOrcamento(categoria: String, valor: String) {
        runCatching { preferenciasGastos.orcamento(ParseGastos.seguro(categoria), ParseGastos.centavos(valor)) }
            .onSuccess { atualizarResumo() }.onFailure { aviso.value = "Informe o orçamento em reais (ex.: 500,00)" }
    }
    fun atualizarResumo() { viewModelScope.launch { resumoGastos.value = gastos.resumo(); aviso.value = gastos.avisos().ifBlank { null } } }
}
