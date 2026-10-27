package com.deivid.secretario

import java.time.LocalDateTime
import org.junit.Assert.*
import org.junit.Test

class CrescimentoTest {
    private fun uso(data: String) = UsoRotina("agenda", LocalDateTime.parse(data))

    @Test fun exigeTresSemanasDistintas() {
        val primeira = uso("2026-10-05T08:00:00")
        assertTrue(PadroesRotina.detectar(listOf(primeira, primeira, primeira)).isEmpty())
        val segunda = uso("2026-10-12T08:00:00")
        assertTrue(PadroesRotina.detectar(listOf(primeira, segunda)).isEmpty())
        assertTrue(PadroesRotina.detectar(listOf(primeira, primeira, segunda)).isEmpty())
        assertEquals(1, PadroesRotina.detectar(listOf(primeira, segunda, uso("2026-10-19T08:45:00"))).size)
    }

    @Test fun naoMisturaDiasHorariosIntencoesOuAnos() {
        val usos = listOf(uso("2026-10-05T08:00:00"), uso("2026-10-12T09:00:00"), uso("2026-10-20T08:00:00"))
        assertTrue(PadroesRotina.detectar(usos).isEmpty())
        assertTrue(PadroesRotina.detectar(usos.map { it.copy(intencao = "comprar") }).isEmpty())
        // Segunda em anos diferentes: a semana é identificada pela data, não só número.
        assertEquals(1, PadroesRotina.detectar(listOf(uso("2024-01-01T08:00:00"),
            uso("2025-12-29T08:00:00"), uso("2026-01-05T08:00:00"))).size)
    }

    @Test fun seletorAlteradoOuAmbiguoNaoReutiliza() {
        val seletor = SeletorReceita(id = "com.exemplo:id/enviar")
        val antigo = ElementoReceita("com.exemplo:id/enviar", "Enviar", false)
        assertEquals(0, seletor.localizar(listOf(antigo)))
        assertNull(seletor.localizar(listOf(antigo.copy(id = "com.exemplo:id/novo"))))
        assertNull(seletor.localizar(listOf(antigo, antigo)))
        assertNull(SeletorReceita(texto = "Enviar").localizar(listOf(antigo.copy(texto = "Publicar"))))
        assertNull(SeletorReceita(texto = "Enviar").localizar(listOf(antigo.copy(editavel = true))))
    }

    @Test fun nenhumValorDigitadoEntraNaReceita() {
        val gravador = GravadorReceita("com.exemplo.social", "mensagem", BloqueioFinanceiro())
        val segredo = "Mensagem privada que muda a cada pedido"
        gravador.registrar("preencher", ElementoReceita("app:id/editor", segredo, true), segredo, true)
        gravador.registrar("tocar", ElementoReceita("", "Enviar", false), sucesso = true)
        val receita = gravador.concluir(true, true)!!
        assertFalse(receita.json().contains(segredo))
        assertEquals(receita, Receita.ler(receita.json()))
        assertEquals(0, receita.passos.first().seletor.localizar(listOf(ElementoReceita("app:id/editor", "outro pedido", true))))
    }

    @Test fun textoDigitadoQueReapareceEmRotuloTambemNaoEGuardado() {
        val g = GravadorReceita("com.exemplo.social", "pesquisa", BloqueioFinanceiro())
        g.registrar("preencher", ElementoReceita("app:id/busca", "", true), "conteúdo privado", true)
        g.registrar("tocar", ElementoReceita("", "Resultado: conteúdo privado", false), sucesso = true)
        assertNull(g.concluir(true, true))
    }

    @Test fun protegeValorJaPresenteNoCampoEIdDinamico() {
        val g = GravadorReceita("com.exemplo.social", "postagem", BloqueioFinanceiro())
        g.protegerValores(listOf("conteúdo\nprivado"))
        g.registrar("tocar", ElementoReceita("", "Prévia: conteúdo privado", false), sucesso = true)
        assertNull(g.concluir(true, true))
        val dinamico = GravadorReceita("com.exemplo.social", "pesquisa", BloqueioFinanceiro())
        dinamico.registrar("preencher", ElementoReceita("app:id/busca", "", true), "segredo", true)
        dinamico.registrar("tocar", ElementoReceita("app:id/segredo", "", false), sucesso = true)
        assertNull(dinamico.concluir(true, true))
    }

    @Test fun exigeSucessoConfirmacaoEAppPermitido() {
        val politica = BloqueioFinanceiro()
        fun gravar(app: String = "com.exemplo.social", sucesso: Boolean = true): GravadorReceita {
            val g = GravadorReceita(app, "mensagem", politica)
            g.registrar("tocar", ElementoReceita("app:id/enviar", "Enviar", false), sucesso = sucesso)
            return g
        }
        assertNull(gravar().concluir(false, true))
        assertNull(gravar().concluir(true, false))
        assertNull(gravar(sucesso = false).concluir(true, true))
        assertNull(gravar("com.nu.production").concluir(true, true))
        val g = gravar()
        politica.acrescentar("com.exemplo.social")
        assertNull(g.concluir(true, true))
    }

    @Test fun campoSemIdEGestoNaoGeramReceita() {
        val g = GravadorReceita("com.exemplo.social", "mensagem", BloqueioFinanceiro())
        g.registrar("preencher", ElementoReceita("", "segredo", true), "segredo", true)
        assertNull(g.concluir(true, true))
        val gesto = GravadorReceita("com.exemplo.social", "outro", BloqueioFinanceiro())
        gesto.registrar("gesto", ElementoReceita("app:id/alvo", "", false), sucesso = true)
        assertNull(gesto.concluir(true, true))
    }
}
