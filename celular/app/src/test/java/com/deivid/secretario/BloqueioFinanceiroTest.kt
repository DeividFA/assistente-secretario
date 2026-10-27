package com.deivid.secretario

import org.junit.Assert.*
import org.junit.Test
import java.util.Locale

class BloqueioFinanceiroTest {
    @Test fun todosOsFixosESubpacotes() {
        val politica = BloqueioFinanceiro()
        BloqueioFinanceiro.FIXOS.forEach {
            assertTrue(it, politica.bloqueado(it))
            assertTrue(it, politica.bloqueado("$it.beta"))
            assertTrue(it, politica.bloqueado("  ${it.uppercase(Locale.ROOT)}  "))
        }
    }
    @Test fun exemplosObrigatorios() {
        val politica = BloqueioFinanceiro()
        listOf("com.nu.production", "br.com.intermedium", "com.picpay").forEach { assertTrue(it, politica.bloqueado(it)) }
        listOf("com.spotify.music", "com.whatsapp").forEach { assertFalse(it, politica.bloqueado(it)) }
    }
    @Test fun heuristicaFinanceira() {
        val politica = BloqueioFinanceiro()
        listOf("bank", "banco", "pay", "wallet", "invest", "cartao", "credito", "cripto", "crypto",
            "mybank", "bankapp", "investimentos", "banking", "superpay", "paypal", "googlepay").forEach {
            assertTrue(it, politica.bloqueado("org.exemplo.$it"))
        }
        assertTrue(politica.bloqueado("org.exemplo.app", "Cartão de crédito"))
    }
    @Test fun semFalsosPositivosObvios() {
        val politica = BloqueioFinanceiro()
        listOf("com.spotify.music", "com.whatsapp", "com.google.android.youtube", "com.instagram.android",
            "org.nextcloud.client", "com.exemplo.original", "com.exemplo.neon", "com.exemplo.rico",
            "com.exemplo.display", "com.exemplo.cosplay", "com.exemplo.microscope", "com.exemplo.player",
            "com.exemplo.paymentwallpaper").forEach { assertFalse(it, politica.bloqueado(it)) }
    }
    @Test fun listaUsuarioSoAcrescentaECopiaNaoAlteraPolitica() {
        val entrada = mutableSetOf("org.privado.app")
        val politica = BloqueioFinanceiro(entrada)
        entrada.clear()
        assertTrue(politica.bloqueado("org.privado.app"))
        politica.acrescentar(" COM.EXEMPLO.LOJA ")
        politica.acrescentar("com.exemplo.loja")
        assertEquals(2, politica.listaUsuario().size)
        assertTrue(politica.bloqueado("com.exemplo.loja"))
        assertTrue(politica.bloqueado("com.nu.production"))
        val copia = politica.listaUsuario().toMutableSet()
        copia.clear()
        assertEquals(2, politica.listaUsuario().size)
    }
    @Test fun origemDesconhecidaBloqueada() {
        val politica = BloqueioFinanceiro()
        assertTrue(politica.bloqueado(null))
        assertTrue(politica.bloqueado("  "))
    }
    @Test(expected = IllegalArgumentException::class) fun recusaAdicaoInvalida() {
        BloqueioFinanceiro().acrescentar("*")
    }
    @Test fun independenteDoLocale() {
        val antes = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("tr-TR"))
            assertTrue(BloqueioFinanceiro().bloqueado("BR.COM.INTERMEDIUM"))
            assertTrue(BloqueioFinanceiro().bloqueado("ORG.APP.INVEST"))
        } finally { Locale.setDefault(antes) }
    }
    @Test fun fronteirasDaListaNaoConfundemApps() {
        val politica = BloqueioFinanceiro(setOf("com.exemplo.loja"))
        assertTrue(politica.bloqueado("com.exemplo.loja.beta"))
        assertFalse(politica.bloqueado("com.exemplo.lojaria"))
        assertFalse(politica.bloqueado("com.nu.productioneditor"))
        assertFalse(politica.bloqueado("org.app.replay"))
        assertFalse(politica.bloqueado("org.app.gameplay"))
    }
    @Test(expected = IllegalArgumentException::class) fun validaListaInicial() {
        BloqueioFinanceiro(setOf(""))
    }
    @Test(expected = UnsupportedOperationException::class) fun fixosImutaveis() {
        (BloqueioFinanceiro.FIXOS as MutableSet<String>).clear()
    }
    @Test fun adicoesNaoEnfraquecemFixosNemHeuristica() {
        val politica = BloqueioFinanceiro()
        repeat(100) { politica.acrescentar("org.usuario.app$it") }
        BloqueioFinanceiro.FIXOS.forEach { assertTrue(it, politica.bloqueado(it)) }
        assertTrue(politica.bloqueado("org.novo.wallet"))
        assertFalse(politica.bloqueado("com.spotify.music"))
        assertFalse(politica.bloqueado("com.whatsapp"))
    }
}
