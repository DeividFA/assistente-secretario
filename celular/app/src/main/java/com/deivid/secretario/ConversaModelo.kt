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
    private val iaGastos = ClienteNuvem(configuracao::nuvem, RegistroAcoes(emptyList()))
    private val lembretes = LembretesCelular(aplicacao)
    private val pc = ClientePc({ evento ->
        viewModelScope.launch {
            when (evento) {
                is EventoPc.Mensagem -> {
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
