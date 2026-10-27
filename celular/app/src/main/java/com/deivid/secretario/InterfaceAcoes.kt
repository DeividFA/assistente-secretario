package com.deivid.secretario

import android.content.Intent
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

sealed class PedidoAcao {
    class Confirmacao(val texto: String, val resposta: CompletableDeferred<Boolean>) : PedidoAcao()
    class Permissao(val nomes: List<String>, val resposta: CompletableDeferred<Boolean>) : PedidoAcao()
    class Abrir(val intent: Intent, val resposta: CompletableDeferred<Unit>) : PedidoAcao()
}

class InterfaceAcoes {
    val pedido = MutableStateFlow<PedidoAcao?>(null)
    private val trava = Mutex()
    suspend fun confirmar(texto: String): Boolean = trava.withLock {
        val resposta = CompletableDeferred<Boolean>()
        pedido.value = PedidoAcao.Confirmacao(texto, resposta)
        try { resposta.await() } finally { pedido.value = null }
    }
    suspend fun permitir(nomes: List<String>): Boolean = trava.withLock {
        val resposta = CompletableDeferred<Boolean>()
        pedido.value = PedidoAcao.Permissao(nomes, resposta)
        try { resposta.await() } finally { pedido.value = null }
    }
    suspend fun abrir(intent: Intent) = trava.withLock {
        val resposta = CompletableDeferred<Unit>()
        pedido.value = PedidoAcao.Abrir(intent, resposta)
        try { resposta.await() } finally { pedido.value = null }
    }
}
