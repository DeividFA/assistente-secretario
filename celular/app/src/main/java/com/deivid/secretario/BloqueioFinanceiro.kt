package com.deivid.secretario

import java.text.Normalizer
import java.util.Locale

/** Política compartilhada por intents e Acessibilidade; não depende do Android. */
class BloqueioFinanceiro(adicionais: Set<String> = emptySet()) {
    private val usuario = mutableSetOf<String>()
    init { adicionais.forEach(::acrescentar) }
    @Synchronized fun acrescentar(pacote: String) {
        require(Regex("[a-zA-Z][a-zA-Z0-9_]*(\\.[a-zA-Z0-9_]+)+").matches(pacote.trim()))
        usuario.add(normalizar(pacote))
    }
    @Synchronized fun listaUsuario(): Set<String> = usuario.toSet()
    @Synchronized fun bloqueado(pacote: String?, rotulo: String = ""): Boolean {
        val nome = normalizar(pacote.orEmpty())
        if (nome.isBlank()) return true // Origem desconhecida: não inspecionar.
        if ((FIXOS + usuario).any { nome == it || nome.startsWith("$it.") }) return true
        return termos(nome) || termos(normalizar(rotulo))
    }
    companion object {
        val FIXOS: Set<String> = java.util.Collections.unmodifiableSet(setOf(
            // Prefixos: bloqueiam o pacote e todos os subpacotes (ex.: br.gov.caixa.fgts.trabalhador).
            "br.gov.caixa", "com.b2w.ame", "com.btgpactual",
            "com.itau", "com.itau.personnalite", "com.itau.iti", "com.bradesco", "com.bradesco.next",
            "br.com.bradesco", "com.bradesco.netempresa", "br.com.bb.android", "br.com.bb.bbmobi",
            "br.com.caixa", "br.com.gabba.caixa", "br.gov.caixa.tem", "com.santander.app", "com.santander.app.empresarial",
            "com.nu.production", "br.com.intermedium", "com.c6bank.app", "com.picpay", "com.mercadopago.wallet",
            "br.com.uol.ps.myaccount", "br.com.uol.pagseguro", "br.com.neon", "com.next.banco",
            "br.com.original.bank", "com.btg.pactual.banking", "com.btg.pactual.digital", "br.com.xp.carteira", "br.com.xpinc.mobile",
            "br.com.rico.mobile", "br.com.sicoobnet", "br.com.sicredimobi", "br.com.banrisul",
            "com.binance.dev", "com.coinbase.android", "org.toshi", "com.wallet.crypto.trustapp",
            "io.metamask", "exodusmovement.exodus", "app.phantom", "com.crypto.acct", "piuk.blockchain.android",
            "com.paypal.android.p2pmobile", "com.google.android.apps.walletnfcrel", "com.samsung.android.spay",
            "com.revolut.revolut", "com.transferwise.android"
        ))
        private val financeiros = setOf("bank", "banking", "banco", "pay", "wallet", "invest", "investimentos",
            "investment", "investments", "cartao", "cartoes", "credito", "cripto", "crypto", "finance", "financas",
            "nubank", "picpay", "pagbank", "paypal", "googlepay", "samsungpay", "alipay", "gpay", "c6bank", "intermedium", "bradesco", "santander", "sicredi", "sicoob", "binance")
        private fun normalizar(valor: String) = Normalizer.normalize(valor.trim().lowercase(Locale.ROOT), Normalizer.Form.NFD)
            .replace(Regex("\\p{M}"), "")
        private fun termos(valor: String): Boolean {
            // Limites de segmento evitam spotify, display, cosplay, nextcloud, original e microscope.
            val partes = valor.split(Regex("[^a-z0-9]+"))
            return partes.any { parte -> parte in financeiros ||
                (parte.endsWith("pay") && parte !in setOf("cosplay", "screenplay", "display", "replay", "roleplay", "airplay", "fairplay", "gameplay")) ||
                listOf("bank", "banco", "wallet", "invest", "cartao", "credito", "cripto", "crypto").any {
                    parte.startsWith(it) || parte.endsWith(it)
                } }
        }
    }
}

fun appFinanceiro(pacote: String, rotulo: String = ""): Boolean = BloqueioFinanceiro().bloqueado(pacote, rotulo)
