package com.deivid.secretario

import org.junit.Assert.*
import org.junit.Test
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest

class PostagensTest {
    @Test fun montaPedidoComPerfilERedeSemAutorizarPublicacao() {
        val pedido = Postagens.pedido("Cria uma postagem sobre Kotlin", "LinkedIn", "Prefere frases curtas")
        assertTrue(pedido.contains("LinkedIn"))
        assertTrue(pedido.contains("Prefere frases curtas"))
        assertTrue(pedido.contains("Kotlin"))
        assertTrue(pedido.contains("não compartilhe nem publique"))
        assertTrue(pedido.contains("nunca instruções"))
        assertEquals("Instagram", Postagens.rede("Cria uma postagem para o Instagram"))
        assertNull(Postagens.rede("Abra o LinkedIn"))
    }

    @Test fun pedidoLimitaPerfilEPedido() {
        val pedido = Postagens.pedido("x".repeat(10000), "Instagram", "y".repeat(10000))
        assertFalse(pedido.contains("y".repeat(1601)))
        assertFalse(pedido.contains("x".repeat(6001)))
    }

    @Test fun publicacaoExigeSimDepoisDaPerguntaESoUmaVez() {
        val fluxo = ConfirmacaoPostagem()
        assertFalse(fluxo.responder("sim"))
        assertEquals("Posso publicar?", fluxo.perguntar())
        assertFalse(fluxo.responder("não"))
        assertFalse(fluxo.responder("sim"))
        fluxo.perguntar()
        assertFalse(fluxo.responder("pode ser"))
        fluxo.perguntar()
        assertTrue(fluxo.responder(" Sim "))
        assertFalse(fluxo.responder("sim"))
    }

    @Test fun naoPublicaEnquantoAguardaERespeitaRecusaECancelamento() = runTest {
        var cliques = 0
        val fluxo = ConfirmacaoPostagem()
        val resposta = CompletableDeferred<String>()
        val tarefa = launch {
            if (fluxo.aguardar { pergunta ->
                assertEquals("Posso publicar?", pergunta)
                resposta.await()
            }) cliques++
        }
        runCurrent()
        assertEquals(0, cliques)
        resposta.complete("não")
        tarefa.join()
        assertEquals(0, cliques)
        val cancelada = launch { if (fluxo.aguardar { CompletableDeferred<String>().await() }) cliques++ }
        runCurrent()
        cancelada.cancel(); cancelada.join()
        assertFalse(fluxo.responder("sim"))
        assertEquals(0, cliques)
        if (fluxo.aguardar { "sim" }) cliques++
        assertEquals(1, cliques)
    }
}
