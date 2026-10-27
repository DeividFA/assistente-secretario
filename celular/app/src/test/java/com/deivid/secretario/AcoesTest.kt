package com.deivid.secretario

import java.time.LocalDateTime
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.*
import org.junit.Test

class AcoesTest {
    private class AcaoFalsa(override val nome: String) : AcaoCelular {
        override val descricao = "Teste"
        override val parametros = buildJsonObject { }
        override suspend fun executar(argumentos: JsonObject) = nome
    }

    @Test fun escolheSomenteNomeRegistrado() {
        val agenda = AcaoFalsa("ler_agenda")
        val evento = AcaoFalsa("criar_evento")
        val registro = RegistroAcoes(listOf(agenda, evento))
        assertSame(agenda, registro.escolher("ler_agenda"))
        assertSame(evento, registro.escolher("criar_evento"))
        assertNull(registro.escolher("executar_comando"))
        assertNull(registro.escolher("LER_AGENDA"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun recusaNomesDuplicados() { RegistroAcoes(listOf(AcaoFalsa("x"), AcaoFalsa("x"))) }

    @Test fun recusaAberturaFinanceiraPorPacoteOuRotulo() {
        assertTrue(appFinanceiro("com.nu.production"))
        assertTrue(appFinanceiro("br.com.intermedium"))
        assertTrue(appFinanceiro("com.exemplo.app", "Banco de crédito"))
        assertFalse(appFinanceiro("com.whatsapp", "WhatsApp"))
        assertFalse(appFinanceiro("com.google.android.calendar", "Agenda"))
    }

    @Test fun interpretaAmanhaComHorario() {
        val agora = LocalDateTime.of(2026, 10, 27, 18, 30)
        assertEquals(LocalDateTime.of(2026, 10, 28, 15, 0), DatasPortugues.interpretar("amanhã às 15h", agora))
        assertEquals(LocalDateTime.of(2026, 10, 28, 15, 45), DatasPortugues.interpretar("amanhã às 15h45", agora))
    }

    @Test fun segundaQueVemSempreFutura() {
        assertEquals(LocalDateTime.of(2026, 11, 2, 9, 0), DatasPortugues.interpretar("segunda que vem", LocalDateTime.of(2026, 10, 27, 10, 0)))
        assertEquals(LocalDateTime.of(2026, 11, 9, 9, 0), DatasPortugues.interpretar("segunda que vem", LocalDateTime.of(2026, 11, 2, 10, 0)))
    }

    @Test fun aceitaIsoEPassagemDeAno() {
        assertEquals(LocalDateTime.of(2027, 1, 1, 15, 0), DatasPortugues.interpretar("amanhã às 15:00", LocalDateTime.of(2026, 12, 31, 23, 0)))
        assertEquals(LocalDateTime.of(2026, 12, 2, 14, 0), DatasPortugues.interpretar("2026-12-02T14:00"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun recusaDataDesconhecida() { DatasPortugues.interpretar("um dia desses") }

    @Test(expected = java.time.DateTimeException::class)
    fun recusaHorarioInvalido() { DatasPortugues.interpretar("amanhã às 25h") }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    @Test fun aguardaConfirmacaoDaInterfaceECancela() = runTest {
        val interfaceAcoes = InterfaceAcoes()
        val resultado = async { interfaceAcoes.confirmar("Criar evento?") }
        runCurrent()
        assertFalse(resultado.isCompleted)
        val pedido = interfaceAcoes.pedido.value as PedidoAcao.Confirmacao
        pedido.resposta.complete(false)
        assertFalse(resultado.await())
        assertNull(interfaceAcoes.pedido.value)
    }
}
