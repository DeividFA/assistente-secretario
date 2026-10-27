package com.deivid.secretario

import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class ParseGastosTest {
    private val hoje = LocalDate.of(2026, 10, 27)
    @Test fun vozComOntem() {
        val item = ParseGastos.texto("gastei 45 reais no mercado ontem", hoje)!!
        assertEquals(4500L, item.valor)
        assertEquals("2026-10-26", item.data)
        assertEquals("mercado", item.estabelecimento)
    }
    @Test fun aluguelComMilharEDecimal() {
        val item = ParseGastos.texto("paguei R$ 1.234,56 de aluguel", hoje)!!
        assertEquals(123456L, item.valor)
        assertEquals("aluguel", item.estabelecimento)
        assertEquals(123456L, ParseGastos.texto("paguei R$ 1234,56 de aluguel", hoje)!!.valor)
    }
    @Test fun compraAprovadaSemGuardarCartao() {
        val item = ParseGastos.notificacao("Compra aprovada! R$ 45,90 no Mercado. Cartão final 1234", hoje)!!
        assertEquals(4590L, item.valor)
        assertEquals("Mercado", item.estabelecimento)
        assertEquals("notificacao", item.origem)
        assertFalse(item.toString().contains("1234"))
        assertFalse(item.toString().contains("Compra aprovada"))
    }
    @Test fun pixEnviado() {
        val item = ParseGastos.notificacao("Pix enviado de R$ 150,00 para Padaria", hoje)!!
        assertEquals(15000L, item.valor)
        assertEquals("Pix", item.forma)
        assertEquals("Padaria", item.estabelecimento)
        assertNull(ParseGastos.notificacao("Pix recebido R$ 150,00", hoje))
        assertNull(ParseGastos.notificacao("Compra não aprovada R$ 45,00", hoje))
        assertNull(ParseGastos.notificacao("Compra aprovada e estornada R$ 45,00", hoje))
        assertNull(ParseGastos.notificacao("Código de acesso 123456", hoje))
    }
    @Test fun csvComMapeamentoVirgulaDecimalEDuplicados() {
        val csv = "Dia;Montante;Loja\n26/10/2026;1.234,56;Mercado\n26/10/2026;1.234,56;Mercado"
        val itens = ParseGastos.csv(csv, mapOf("data" to "Dia", "valor" to "Montante", "estabelecimento" to "Loja"))
        assertEquals(1, itens.size)
        assertEquals(123456L, itens.single().valor)
        assertEquals("2026-10-26", itens.single().data)
        val aspas = "data,valor,loja\n2026-10-26,\"45,90\",\"Mercado, Centro\""
        assertEquals(4590L, ParseGastos.csv(aspas, mapOf("data" to "data", "valor" to "valor", "estabelecimento" to "loja")).single().valor)
    }
    @Test fun valoresInvalidosNuncaArredondados() {
        listOf("45.90", "1,234", "-1", "0", "NaN", "1e3", "99999999999999999999999").forEach { valor ->
            assertTrue(valor, runCatching { ParseGastos.centavos(valor) }.isFailure)
        }
        assertTrue(runCatching { ParseGastos.csv("data;valor\n30/02/2026;45,00", mapOf("data" to "data", "valor" to "valor")) }.isFailure)
    }
}
