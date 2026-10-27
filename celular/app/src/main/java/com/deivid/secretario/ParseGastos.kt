package com.deivid.secretario

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale

data class RascunhoGasto(val data: String, val valor: Long, val estabelecimento: String = "",
    val categoria: String = "Outros", val forma: String = "", val origem: String = "voz")

/** Só campos extraídos saem deste parser; texto de notificação nunca é persistido. */
object ParseGastos {
    private val dinheiro = Regex("(?:R\\$\\s*((?:\\d{1,3}(?:\\.\\d{3})+|\\d+)(?:,\\d{2})?)(?!\\d|[.,]\\d)|(?<![\\d.,])(\\d+(?:,\\d{2})?)\\s*reais)", RegexOption.IGNORE_CASE)
    fun centavos(texto: String): Long {
        val limpo = texto.trim().removePrefix("R$").trim()
        require(Regex("(?:\\d{1,3}(?:\\.\\d{3})+|\\d+)(?:,\\d{1,2})?").matches(limpo))
        val partes = limpo.replace(".", "").split(',')
        val valor = Math.addExact(Math.multiplyExact(partes[0].toLong(), 100L),
            partes.getOrNull(1)?.padEnd(2, '0')?.toLong() ?: 0L)
        require(valor in 1..1_000_000_000_000L)
        return valor
    }
    fun reais(valor: Long) = "R$ ${valor / 100},${(valor % 100).toString().padStart(2, '0')}"
    fun seguro(texto: String) = texto.replace(Regex("\\d{4,}|[\\r\\n]"), "").take(120).trim()
    fun texto(texto: String, hoje: LocalDate = LocalDate.now(), origem: String = "voz"): RascunhoGasto? {
        val valor = dinheiro.find(texto) ?: return null
        val numero = valor.groupValues.drop(1).first { it.isNotBlank() }
        val dataExplicita = Regex("\\b(\\d{4}-\\d{2}-\\d{2}|\\d{2}/\\d{2}/\\d{4})\\b").find(texto)?.value
        val data = when {
            dataExplicita != null -> if ('/' in dataExplicita) LocalDate.parse(dataExplicita, DateTimeFormatter.ofPattern("dd/MM/uuuu").withResolverStyle(java.time.format.ResolverStyle.STRICT)) else LocalDate.parse(dataExplicita)
            Regex("\\bontem\\b", RegexOption.IGNORE_CASE).containsMatchIn(texto) -> hoje.minusDays(1)
            else -> hoje
        }
        val local = Regex("(?:\\bno|\\bna|\\bem|\\bde|\\bpara)\\s+([\\p{L}][\\p{L} .'-]*?)(?=\\s+ontem|\\s+hoje|[.!]|$)", RegexOption.IGNORE_CASE)
            .find(texto.substring(valor.range.last + 1))?.groupValues?.get(1).orEmpty()
        return RascunhoGasto(data.toString(), centavos(numero), seguro(local), forma = if (texto.contains("pix", true)) "Pix" else "", origem = origem)
    }
    fun notificacao(texto: String, hoje: LocalDate = LocalDate.now()): RascunhoGasto? {
        val normal = java.text.Normalizer.normalize(texto.lowercase(Locale.ROOT), java.text.Normalizer.Form.NFD).replace(Regex("\\p{M}"), "")
        if (!Regex("compra.{0,40}aprovad[ao]|aprovad[ao].{0,40}compra|pix\\s+enviado").containsMatchIn(normal) ||
            Regex("recusad|cancelad|estorn|nao aprovad|agendad").containsMatchIn(normal) || !texto.contains("R$")) return null
        return texto(texto, hoje, "notificacao")
    }
    fun csv(conteudo: String, colunas: Map<String, String>): List<RascunhoGasto> {
        val linhas = conteudo.lineSequence().filter { it.isNotBlank() }.toList()
        require(linhas.isNotEmpty())
        val separador = if (';' in linhas.first()) ';' else ','
        val cabecalho = linhaCsv(linhas.first().removePrefix("\uFEFF"), separador)
        fun campo(linha: List<String>, chave: String): String {
            val nome = colunas[chave] ?: return ""
            val indice = cabecalho.indexOf(nome)
            require(indice >= 0) { "Coluna ausente: $nome" }
            return linha.getOrElse(indice) { error("Linha incompleta") }
        }
        require(colunas.keys.containsAll(listOf("data", "valor")))
        return linhas.drop(1).map { linha ->
            val campos = linhaCsv(linha, separador)
            val data = campo(campos, "data")
            val dia = if ('/' in data) LocalDate.parse(data, DateTimeFormatter.ofPattern("dd/MM/uuuu").withResolverStyle(java.time.format.ResolverStyle.STRICT)) else LocalDate.parse(data)
            RascunhoGasto(dia.toString(), centavos(campo(campos, "valor")), seguro(campo(campos, "estabelecimento")),
                seguro(campo(campos, "categoria")).ifBlank { "Outros" }, seguro(campo(campos, "forma")), "csv")
        }.distinct()
    }
    private fun linhaCsv(linha: String, separador: Char): List<String> {
        val campos = mutableListOf<String>(); val atual = StringBuilder(); var aspas = false; var i = 0
        while (i < linha.length) {
            val c = linha[i++]
            if (c == '"') {
                if (aspas && i < linha.length && linha[i] == '"') { atual.append('"'); i++ } else aspas = !aspas
            } else if (c == separador && !aspas) { campos.add(atual.toString().trim()); atual.clear() } else atual.append(c)
        }
        require(!aspas) { "Aspas incompletas no CSV" }
        campos.add(atual.toString().trim()); return campos
    }
}


