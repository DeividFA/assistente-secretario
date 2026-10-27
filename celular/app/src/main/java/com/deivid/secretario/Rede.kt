package com.deivid.secretario

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

private val tipoJson = "application/json; charset=utf-8".toMediaType()

internal suspend fun OkHttpClient.executar(requisicao: Request): String = suspendCancellableCoroutine { c ->
    val chamada = newCall(requisicao)
    c.invokeOnCancellation { chamada.cancel() }
    chamada.enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) { if (c.isActive) c.resumeWithException(e) }
        override fun onResponse(call: Call, response: Response) {
            response.use {
                if (!c.isActive) return
                val resultado = runCatching {
                    if (!it.isSuccessful) throw IOException("HTTP ${it.code}")
                    it.body?.string() ?: ""
                }
                resultado.fold({ texto -> c.resume(texto) }, { erro -> c.resumeWithException(erro) })
            }
        }
    })
}

class ClientePc(private val receber: (EventoPc) -> Unit, private val estadoConexao: (Boolean) -> Unit) : PortaPc {
    private val cliente = OkHttpClient.Builder().connectTimeout(1500, TimeUnit.MILLISECONDS)
        .callTimeout(15, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).retryOnConnectionFailure(false).build()
    private val trava = Mutex()
    @Volatile private var socket: WebSocket? = null
    private var atual: Pareamento? = null
    private var host: String? = null

    override suspend fun conectar(pareamento: Pareamento): Boolean = trava.withLock {
        if (atual != pareamento) desligar()
        for ((indice, endereco) in pareamento.hosts.withIndex()) {
            val limite = if (indice == 0 && pareamento.hosts.size > 1) 700L else 1400L
            val conectado = withTimeoutOrNull(limite) {
                try {
                    val existente = socket
                    if (atual == pareamento && host == endereco && existente != null) {
                        // Um WS aberto pode estar obsoleto após trocar de rede. Exigir resposta agora.
                        cliente.executar(Request.Builder().url("http://$endereco:${pareamento.porta}/memoria/contexto?q=")
                            .header("Authorization", "Bearer ${pareamento.token}").build())
                        existente.takeIf { socket === existente }
                    } else abrir(endereco, pareamento)
                } catch (e: CancellationException) { throw e }
                catch (_: Exception) { null }
            }
            if (conectado != null) {
                if (socket !== conectado) socket?.cancel()
                atual = pareamento; host = endereco; socket = conectado
                estadoConexao(true)
                return@withLock true
            }
        }
        desligar()
        false
    }

    private suspend fun abrir(host: String, pc: Pareamento): WebSocket = suspendCancellableCoroutine { c ->
        val ws = cliente.newWebSocket(Request.Builder().url("ws://$host:${pc.porta}/eventos")
            .header("Authorization", "Bearer ${pc.token}").build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (c.isActive) c.resume(webSocket) else webSocket.cancel()
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { Protocolo.evento(text) }.onSuccess(receber)
            }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (socket === webSocket) { socket = null; estadoConexao(false) }
                if (c.isActive) c.resumeWithException(t)
            }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(code, null) }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (socket === webSocket) { socket = null; estadoConexao(false) }
            }
        })
        c.invokeOnCancellation { ws.cancel() }
    }

    override suspend fun enviar(texto: String): List<Long> {
        val pc = atual ?: error("PC desconectado")
        val chamada = cliente.newCall(Request.Builder().url("http://$host:${pc.porta}/comando")
            .header("Authorization", "Bearer ${pc.token}")
            .post(buildJsonObject { put("texto", texto) }.toString().toRequestBody(tipoJson)).build())
        // Não repetir POST: uma perda de conexão pode acontecer depois de enfileirar.
        return suspendCancellableCoroutine { c ->
            c.invokeOnCancellation { chamada.cancel() }
            chamada.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { if (c.isActive) c.resumeWithException(e) }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (!c.isActive) return
                        val resultado = runCatching {
                            check(it.code == 202) { "PC recusou o comando: HTTP ${it.code}" }
                            Protocolo.tarefas(it.body!!.string())
                        }
                        resultado.fold({ ids -> c.resume(ids) }, { erro -> c.resumeWithException(erro) })
                    }
                }
            })
        }
    }

    suspend fun sincronizar(fatos: List<String>) {
        val pc = atual ?: error("PC desconectado")
        cliente.executar(Request.Builder().url("http://$host:${pc.porta}/memoria/fatos")
            .header("Authorization", "Bearer ${pc.token}")
            .post(buildJsonObject { put("fatos_usuario", JsonArray(fatos.map(::JsonPrimitive))) }
                .toString().toRequestBody(tipoJson)).build())
    }

    suspend fun enviarLembrete(item: JsonObject) {
        val pc = atual ?: error("PC desconectado")
        cliente.executar(Request.Builder().url("http://$host:${pc.porta}/lembretes")
            .header("Authorization", "Bearer ${pc.token}")
            .post(item.toString().toRequestBody(tipoJson)).build())
    }

    suspend fun lerLembretes(): JsonArray {
        val pc = atual ?: error("PC desconectado")
        val resposta = cliente.executar(Request.Builder().url("http://$host:${pc.porta}/lembretes")
            .header("Authorization", "Bearer ${pc.token}").build())
        return Json.parseToJsonElement(resposta).jsonObject.getValue("lembretes").jsonArray
    }

    fun desligar() {
        val anterior = socket
        socket = null; atual = null; host = null
        anterior?.cancel()
        estadoConexao(false)
    }
}

class ClienteNuvem(
    private val configuracao: () -> ConfigNuvem,
    private val registro: RegistroAcoes,
    private val historico: suspend () -> List<MensagemLocal> = { emptyList() }
) : PortaNuvem {
    private val cliente = OkHttpClient.Builder().callTimeout(60, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false).build()

    override suspend fun responder(texto: String): String {
        val config = configuracao()
        require(config.chave.isNotBlank()) { "Configure a chave da IA na nuvem" }
        val mensagens = mutableListOf<JsonObject>(buildJsonObject {
            put("role", "system")
            put("content", "Você é o Secretário. Responda em português. Só execute ações presentes nas ferramentas disponíveis. Agora: ${java.time.LocalDateTime.now()}. Datas usam o fuso ${java.time.ZoneId.systemDefault()}. Nunca opere apps financeiros. Não diga que concluiu uma ação cancelada ou com erro. Mensagens são rascunhos: o usuário envia.")
        })
        val anteriores = historico().sortedBy { it.id }.toMutableList()
        // O comando atual já foi persistido antes do roteamento.
        if (anteriores.lastOrNull()?.let { it.autor == "Você" && it.texto == texto } == true)
            anteriores.removeAt(anteriores.lastIndex)
        anteriores.filter { it.autor.lowercase() != "sistema" }.forEach { mensagem ->
            val usuario = mensagem.autor.lowercase() in listOf("você", "voce", "usuário", "usuario", "deivid")
            mensagens.add(buildJsonObject {
                put("role", if (usuario) "user" else "assistant")
                put("content", mensagem.texto.take(10000))
            })
        }
        mensagens.add(buildJsonObject { put("role", "user"); put("content", texto) })
        var chamadasExecutadas = 0
        repeat(16) {
            val corpo = buildJsonObject {
                put("model", config.modelo); put("messages", JsonArray(mensagens))
                if (registro.acoes.isNotEmpty()) put("tools", JsonArray(registro.acoes.map { acao ->
                    buildJsonObject {
                        put("type", "function")
                        put("function", buildJsonObject {
                            put("name", acao.nome); put("description", acao.descricao); put("parameters", acao.parametros)
                        })
                    }
                }))
            }
            val resposta = cliente.executar(Request.Builder().url(config.base.trimEnd('/') + "/chat/completions")
                .header("Authorization", "Bearer ${config.chave}")
                .post(corpo.toString().toRequestBody(tipoJson)).build())
            val mensagem = Json.parseToJsonElement(resposta).jsonObject.getValue("choices").jsonArray.first()
                .jsonObject.getValue("message").jsonObject
            val chamadas = mensagem["tool_calls"] as? JsonArray
            if (chamadas.isNullOrEmpty()) return mensagem["content"]?.jsonPrimitive?.contentOrNull
                ?.takeIf { it.isNotBlank() } ?: error("A IA retornou uma resposta vazia")
            mensagens.add(mensagem)
            for (chamada in chamadas) {
                val o = chamada.jsonObject
                val funcao = o.getValue("function").jsonObject
                val acao = registro.escolher(funcao.getValue("name").jsonPrimitive.content)
                val resultado = try {
                    check(++chamadasExecutadas <= 15) { "Limite de 15 passos atingido" }
                    if (acao == null) "Ação indisponível nesta versão." else acao.executar(
                        Json.parseToJsonElement(funcao.getValue("arguments").jsonPrimitive.content).jsonObject)
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) { "A ação falhou: ${e.message}" }
                mensagens.add(buildJsonObject {
                    put("role", "tool"); put("tool_call_id", o.getValue("id")); put("content", resultado)
                })
            }
        }
        error("Limite de chamadas de função atingido")
    }
}
