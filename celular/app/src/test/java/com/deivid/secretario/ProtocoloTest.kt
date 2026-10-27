package com.deivid.secretario

import org.junit.Assert.*
import org.junit.Test

class ProtocoloTest {
    private val token = "ab".repeat(32)
    private fun qr(lan: String = "\"192.168.1.8\"", tailscale: String = "\"100.80.2.3\"", porta: String = "8765", segredo: String = token) =
        """{"host_lan":$lan,"host_tailscale":$tailscale,"porta":$porta,"token":"$segredo"}"""

    @Test fun `le o QR exato da ponte e preserva o token`() {
        val pc = Pareamento.ler(qr())
        assertEquals(listOf("192.168.1.8", "100.80.2.3"), pc.hosts)
        assertEquals(8765, pc.porta)
        assertEquals(token, pc.token)
        assertEquals(pc, Pareamento.ler(pc.json()))
    }
    @Test fun `aceita host nulo em ambas as posicoes`() {
        assertEquals(listOf("100.80.2.3"), Pareamento.ler(qr(lan = "null")).hosts)
        assertEquals(listOf("192.168.1.8"), Pareamento.ler(qr(tailscale = "null")).hosts)
    }
    @Test fun `rejeita QR ausente malformado ou com enderecos fora do contrato`() {
        listOf("{}", "texto", qr("null", "null"), qr("\"8.8.8.8\""),
            qr("\"192.168.1.999\""), qr("\"http://192.168.1.8\""),
            qr(porta = "0"), qr(porta = "65536"), qr(porta = "\"8765\""), qr(segredo = "curto"))
            .forEach { entrada -> assertTrue(entrada, runCatching { Pareamento.ler(entrada) }.isFailure) }
    }
    @Test fun `mensagem usa autor e texto sem campos inventados`() {
        assertEquals(EventoPc.Mensagem("Secretário", "Olá"), Protocolo.evento(
            """{"evento":"mensagem","autor":"Secretário","texto":"Olá","aparelho":7,"tarefa":15}"""))
    }
    @Test fun `estado e fila seguem eventos IPC`() {
        assertEquals(EventoPc.Estado("pensando"), Protocolo.evento("""{"evento":"estado","estado":"pensando"}"""))
        assertEquals(EventoPc.Fila(listOf(TarefaPc(12, "abra a agenda", "pendente"))), Protocolo.evento(
            """{"evento":"fila","tarefas":[{"id":12,"comando":"abra a agenda","status":"pendente","motor":"claude","origem":"celular"}]}"""))
        assertEquals(EventoPc.Fila(emptyList()), Protocolo.evento("""{"evento":"fila","tarefas":[]}"""))
    }
    @Test fun `eventos futuros sao ignoraveis e mensagens invalidas nao viram texto`() {
        assertEquals(EventoPc.Outro("motores"), Protocolo.evento("""{"evento":"motores","motores":[]}"""))
        assertTrue(runCatching { Protocolo.evento("""{"evento":"mensagem","texto":"sem autor"}""") }.isFailure)
        assertTrue(runCatching { Protocolo.evento("não JSON") }.isFailure)
    }
    @Test fun `aceite e lista de tarefas nao sao uma resposta de conversa`() {
        assertEquals(listOf(11L, 12L), Protocolo.tarefas("""{"origem":"celular","tarefas":[11,12]}"""))
    }
}
