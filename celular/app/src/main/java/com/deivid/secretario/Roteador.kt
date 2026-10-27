package com.deivid.secretario

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

interface PortaPc {
    suspend fun conectar(pareamento: Pareamento): Boolean
    suspend fun enviar(texto: String): List<Long>
}

fun interface PortaNuvem {
    suspend fun responder(texto: String): String
}

sealed interface Resposta {
    data class Pc(val tarefas: List<Long>) : Resposta
    data class Nuvem(val texto: String) : Resposta
}

class Roteador(private val pc: PortaPc, private val nuvem: PortaNuvem) {
    suspend fun enviar(texto: String, pareamento: Pareamento?): Resposta {
        require(texto.isNotBlank() && texto.length <= 10000) { "Envie entre 1 e 10000 caracteres" }
        val conectado = pareamento != null && withTimeoutOrNull(1500) {
            try { pc.conectar(pareamento) } catch (e: CancellationException) { throw e }
            catch (_: Exception) { false }
        } == true
        // Após o envio, uma falha pode ser apenas a perda do recibo. Não duplicar na nuvem.
        return if (conectado) Resposta.Pc(pc.enviar(texto.trim()))
        else Resposta.Nuvem(nuvem.responder(texto.trim()))
    }
}
