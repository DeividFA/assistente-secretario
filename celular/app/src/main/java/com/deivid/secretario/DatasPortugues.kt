package com.deivid.secretario

import java.text.Normalizer
import java.time.DayOfWeek
import java.time.LocalDateTime
import java.time.temporal.TemporalAdjusters

object DatasPortugues {
    fun interpretar(texto: String, agora: LocalDateTime = LocalDateTime.now()): LocalDateTime {
        runCatching { return LocalDateTime.parse(texto) }
        val t = Normalizer.normalize(texto.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{M}"), "")
        val hora = Regex("(?:as\\s+)?(\\d{1,2})(?:h(?:(\\d{2}))?|:(\\d{2}))").find(t)
        val h = hora?.groupValues?.get(1)?.toInt() ?: 9
        val m = hora?.let { (it.groupValues[2].ifEmpty { it.groupValues[3] }).ifEmpty { "0" }.toInt() } ?: 0
        val dias = listOf("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
        val dia = dias.indexOfFirst { t.contains(it) }
        val data = when {
            t.contains("amanha") -> agora.toLocalDate().plusDays(1)
            t.contains("hoje") -> agora.toLocalDate()
            dia >= 0 -> agora.toLocalDate().with(TemporalAdjusters.next(DayOfWeek.of(dia + 1)))
            else -> throw IllegalArgumentException("Informe a data em português ou ISO AAAA-MM-DDTHH:MM")
        }
        return data.atTime(h, m)
    }
}
