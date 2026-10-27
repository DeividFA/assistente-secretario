package com.deivid.secretario

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Pacotes reais da Play Store brasileira (conferidos pelo revisor). */
class BloqueioReaisTest {
    private val bloqueio = BloqueioFinanceiro()

    @Test fun bancosEFintechsReais() {
        listOf("com.itau", "com.itau.iti", "com.bradesco", "br.com.bb.android", "br.com.gabba.Caixa",
            "br.gov.caixa.tem", "br.gov.caixa.fgts.trabalhador", "com.santander.app", "com.mercadopago.wallet",
            "com.c6bank.app", "br.com.neon", "br.com.uol.ps.myaccount", "br.com.intermedium", "com.nu.production",
            "br.com.bancopan.cartoes", "com.willbank", "com.b2w.ame", "com.picpay", "br.com.original.bank",
            "com.btgpactual.pangea", "br.com.xp.carteira", "com.sicredi.mobile", "br.com.sicoob.app",
            "com.binance.dev", "com.paypal.android.p2pmobile", "com.google.android.apps.walletnfcrel",
        ).filterNot { bloqueio.bloqueado(it) }.let { assertTrue("deveria bloquear $it", it.isEmpty()) }
    }

    @Test fun appsComunsLiberados() {
        listOf("com.whatsapp", "com.instagram.android", "com.linkedin.android", "com.spotify.music",
            "com.google.android.calendar", "com.google.android.apps.maps", "com.google.android.gm",
            "com.twitter.android", "com.google.android.youtube", "com.android.chrome", "com.ubercab",
            "com.ifood.webapp", "com.netflix.mediaclient", "com.microsoft.teams", "org.telegram.messenger",
        ).filter { bloqueio.bloqueado(it) }.let { assertTrue("não deveria bloquear $it", it.isEmpty()) }
    }
}
