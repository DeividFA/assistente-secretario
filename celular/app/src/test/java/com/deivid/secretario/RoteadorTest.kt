package com.deivid.secretario

import java.io.IOException
import kotlinx.coroutines.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class RoteadorTest {
    private val pareamento = Pareamento("192.168.0.4", null, 8765, "ab".repeat(32))
    private class PcFalso(var atraso: Long = 0, var disponivel: Boolean = true) : PortaPc {
        var enviados = 0
        var tentativas = 0
        var falharEnvio = false
        var falharConexao = false
        override suspend fun conectar(pareamento: Pareamento): Boolean {
            tentativas++
            delay(atraso)
            if (falharConexao) throw IOException("offline")
            return disponivel
        }
        override suspend fun enviar(texto: String): List<Long> {
            enviados++
            if (falharEnvio) throw IOException("recibo perdido")
            return listOf(42)
        }
    }
    @Test fun `PC respondendo dentro do prazo recebe comando sem nuvem`() = runTest {
        val pc = PcFalso(atraso = 1499)
        val roteador = Roteador(pc) { error("Não deveria usar a nuvem") }
        assertEquals(Resposta.Pc(listOf(42L)), roteador.enviar("olá", pareamento))
        assertEquals(1, pc.enviados)
    }
    @Test fun `timeout de 1500 ms cancela tentativa antes de usar nuvem`() = runTest {
        val pc = PcFalso(atraso = 5000)
        var nuvem = 0
        val inicio = testScheduler.currentTime
        assertEquals(Resposta.Nuvem("resposta"), Roteador(pc) { nuvem++; "resposta" }.enviar("olá", pareamento))
        assertEquals(1500L, testScheduler.currentTime - inicio)
        assertEquals(0, pc.enviados)
        assertEquals(1, nuvem)
    }
    @Test fun `sem pareamento vai direto a nuvem`() = runTest {
        val pc = PcFalso()
        assertEquals(Resposta.Nuvem("ok"), Roteador(pc) { "ok" }.enviar("olá", null))
        assertEquals(0, pc.tentativas)
    }
    @Test fun `falha ou indisponibilidade da conexao usa nuvem`() = runTest {
        for (pc in listOf(PcFalso(disponivel = false), PcFalso().apply { falharConexao = true })) {
            assertEquals(Resposta.Nuvem("ok"), Roteador(pc) { "ok" }.enviar("olá", pareamento))
            assertEquals(0, pc.enviados)
        }
    }
    @Test fun `perda do recibo depois de enviar nao duplica o comando na nuvem`() = runTest {
        val pc = PcFalso().apply { falharEnvio = true }
        var nuvem = 0
        try {
            Roteador(pc) { nuvem++; "ok" }.enviar("olá", pareamento)
            fail("Deveria informar a falha")
        } catch (_: IOException) { }
        assertEquals(1, pc.enviados)
        assertEquals(0, nuvem)
    }
    @Test fun `cancelamento do chamador nao aciona fallback`() = runTest {
        var nuvem = 0
        val pc = PcFalso(atraso = 5000)
        val trabalho = launch { Roteador(pc) { nuvem++; "ok" }.enviar("olá", pareamento) }
        testScheduler.runCurrent()
        trabalho.cancelAndJoin()
        assertEquals(0, nuvem)
        assertEquals(0, pc.enviados)
    }
    @Test fun `mensagem vazia nao chama nenhum destino`() = runTest {
        val pc = PcFalso()
        try { Roteador(pc) { error("nuvem") }.enviar(" ", pareamento); fail() }
        catch (_: IllegalArgumentException) { }
        assertEquals(0, pc.tentativas)
    }
}
