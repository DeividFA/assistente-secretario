package com.deivid.secretario

import android.Manifest
import android.content.ClipData
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.AlarmClock
import android.provider.CalendarContract
import androidx.core.content.ContextCompat
import java.time.ZoneId
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

private fun JsonObject.texto(chave: String) = get(chave)?.jsonPrimitive?.contentOrNull.orEmpty()
private fun esquema(vararg campos: String) = buildJsonObject {
    put("type", "object")
    put("properties", buildJsonObject { campos.forEach { put(it, buildJsonObject { put("type", "string") }) } })
    put("required", JsonArray(campos.filter { it !in listOf("imagem", "fim", "assunto") }.map(::JsonPrimitive)))
    put("additionalProperties", false)
}

class AmbienteAcoes(
    val contexto: Context,
    val confirmar: suspend (String) -> Boolean,
    val permitir: suspend (List<String>) -> Boolean,
    val abrir: suspend (Intent) -> Unit,
    val lembretes: LembretesCelular
) {
    suspend fun permissao(vararg nomes: String) {
        val faltam = nomes.filter { ContextCompat.checkSelfPermission(contexto, it) != PackageManager.PERMISSION_GRANTED }
        check(faltam.isEmpty() || permitir(faltam)) { "Permissão recusada" }
    }
}

abstract class AcaoIntent(protected val ambiente: AmbienteAcoes) : AcaoCelular {
    protected suspend fun abrir(intent: Intent): String { ambiente.abrir(intent); return "Aberto no celular." }
}

class AbrirApp(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "abrir_app"
    override val descricao = "Abre um app pelo pacote Android. Nunca use apps de banco ou finanças."
    override val parametros = esquema("pacote")
    override suspend fun executar(argumentos: JsonObject): String {
        val pacote = argumentos.texto("pacote")
        val politica = BloqueioFinanceiro(ambiente.contexto.getSharedPreferences("bloqueio_acessibilidade", Context.MODE_PRIVATE)
            .getStringSet("adicionais", emptySet()).orEmpty())
        require(pacote.isNotBlank() && !politica.bloqueado(pacote)) { "App financeiro ou pacote inválido" }
        val info = ambiente.contexto.packageManager.getApplicationInfo(pacote, 0)
        require(!politica.bloqueado(pacote, ambiente.contexto.packageManager.getApplicationLabel(info).toString())) { "App financeiro" }
        return abrir(ambiente.contexto.packageManager.getLaunchIntentForPackage(pacote) ?: error("App não encontrado"))
    }
}

class LerAgenda(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "ler_agenda"
    override val descricao = "Lê eventos de todos os calendários, incluindo Google Agenda. Data em português ou ISO."
    override val parametros = esquema("quando")
    override suspend fun executar(argumentos: JsonObject): String {
        val inicio = DatasPortugues.interpretar(argumentos.texto("quando")).toLocalDate().atStartOfDay()
        ambiente.permissao(Manifest.permission.READ_CALENDAR)
        return withContext(Dispatchers.IO) {
            val uri = CalendarContract.Instances.CONTENT_URI.buildUpon()
            android.content.ContentUris.appendId(uri, inicio.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli())
            android.content.ContentUris.appendId(uri, inicio.plusDays(1).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli())
            val eventos = mutableListOf<String>()
            ambiente.contexto.contentResolver.query(uri.build(), arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN), null, null, "begin ASC")?.use { c ->
                while (c.moveToNext()) eventos.add("${java.time.Instant.ofEpochMilli(c.getLong(1)).atZone(ZoneId.systemDefault()).toLocalTime()} — ${c.getString(0)}")
            }
            eventos.joinToString("\n").ifEmpty { "Nenhum evento nesse dia." }
        }
    }
}

class CriarEvento(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "criar_evento"
    override val descricao = "Cria evento após confirmação na tela. Início/fim em português ou ISO; fim opcional (uma hora)."
    override val parametros = esquema("titulo", "quando", "fim")
    override suspend fun executar(argumentos: JsonObject): String {
        val titulo = argumentos.texto("titulo").also { require(it.isNotBlank()) }
        val inicio = DatasPortugues.interpretar(argumentos.texto("quando"))
        val fim = argumentos.texto("fim").takeIf { it.isNotBlank() }?.let { DatasPortugues.interpretar(it) } ?: inicio.plusHours(1)
        require(fim > inicio)
        if (!ambiente.confirmar("Criar evento: $titulo\n$inicio até $fim?")) return "Evento cancelado."
        ambiente.permissao(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
        return withContext(Dispatchers.IO) {
            val calendario = ambiente.contexto.contentResolver.query(CalendarContract.Calendars.CONTENT_URI,
                arrayOf(CalendarContract.Calendars._ID), "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ? AND ${CalendarContract.Calendars.VISIBLE} = 1",
                arrayOf(CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR.toString()), null)?.use { if (it.moveToFirst()) it.getLong(0) else null } ?: error("Nenhum calendário gravável")
            val valores = ContentValues().apply {
                put(CalendarContract.Events.CALENDAR_ID, calendario); put(CalendarContract.Events.TITLE, titulo)
                put(CalendarContract.Events.DTSTART, inicio.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli())
                put(CalendarContract.Events.DTEND, fim.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli())
                put(CalendarContract.Events.EVENT_TIMEZONE, ZoneId.systemDefault().id)
            }
            check(ambiente.contexto.contentResolver.insert(CalendarContract.Events.CONTENT_URI, valores) != null)
            "Evento criado."
        }
    }
}

class AlarmeTimer(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "alarme_timer"
    override val descricao = "Abre alarme (tipo alarme, valor HH:MM) ou timer (tipo timer, valor em segundos), com interface do relógio."
    override val parametros = esquema("tipo", "valor", "texto")
    override suspend fun executar(argumentos: JsonObject): String {
        ambiente.permissao("com.android.alarm.permission.SET_ALARM")
        val intent = when (argumentos.texto("tipo")) {
            "timer" -> Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH, argumentos.texto("valor").toInt().also { require(it > 0) })
            "alarme" -> {
                val hora = java.time.LocalTime.parse(argumentos.texto("valor"))
                Intent(AlarmClock.ACTION_SET_ALARM).putExtra(AlarmClock.EXTRA_HOUR, hora.hour).putExtra(AlarmClock.EXTRA_MINUTES, hora.minute)
            }
            else -> error("Tipo inválido")
        }
        return abrir(intent.putExtra(AlarmClock.EXTRA_MESSAGE, argumentos.texto("texto")).putExtra(AlarmClock.EXTRA_SKIP_UI, false))
    }
}

class AbrirMapa(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "abrir_mapa"
    override val descricao = "Abre mapa ou rota; tipo mapa ou rota, destino endereço."
    override val parametros = esquema("tipo", "destino")
    override suspend fun executar(argumentos: JsonObject): String {
        val destino = Uri.encode(argumentos.texto("destino").also { require(it.isNotBlank()) })
        val uri = if (argumentos.texto("tipo") == "rota") "https://www.google.com/maps/dir/?api=1&destination=$destino" else "geo:0,0?q=$destino"
        return abrir(Intent(Intent.ACTION_VIEW, Uri.parse(uri)))
    }
}

class PrepararMensagem(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "preparar_mensagem"
    override val descricao = "Prepara rascunho SMS, WhatsApp ou email após confirmação. O usuário envia. tipo sms/whatsapp/email."
    override val parametros = esquema("tipo", "destino", "texto", "assunto")
    override suspend fun executar(argumentos: JsonObject): String {
        val tipo = argumentos.texto("tipo"); val destino = argumentos.texto("destino"); val texto = argumentos.texto("texto")
        require(destino.isNotBlank() && texto.isNotBlank())
        require(tipo in listOf("sms", "whatsapp", "email"))
        if (!ambiente.confirmar("Preparar $tipo para $destino\n${argumentos.texto("assunto")}\n$texto? Você fará o envio.")) return "Rascunho cancelado."
        val intent = when (tipo) {
            "sms" -> Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:${Uri.encode(destino)}")).putExtra("sms_body", texto)
            "email" -> Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:${Uri.encode(destino)}")).putExtra(Intent.EXTRA_SUBJECT, argumentos.texto("assunto")).putExtra(Intent.EXTRA_TEXT, texto)
            else -> Intent(Intent.ACTION_VIEW, Uri.parse("https://wa.me/${destino.filter { it.isDigit() }}?text=${Uri.encode(texto)}"))
        }
        return abrir(intent)
    }
}

class Compartilhar(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "compartilhar"
    override val descricao = "Compartilha texto e imagem content:// opcional da galeria. Mostra seletor de app; usuário publica."
    override val parametros = esquema("texto", "imagem")
    override suspend fun executar(argumentos: JsonObject): String {
        val intent = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, argumentos.texto("texto"))
        argumentos.texto("imagem").takeIf { it.isNotBlank() }?.let {
            val uri = Uri.parse(it); require(uri.scheme == "content")
            intent.type = "image/*"; intent.putExtra(Intent.EXTRA_STREAM, uri)
            intent.clipData = ClipData.newRawUri("Imagem", uri)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        if (!ambiente.confirmar("Compartilhar ${argumentos.texto("texto")}\n${argumentos.texto("imagem")}?")) return "Compartilhamento cancelado."
        return abrir(Intent.createChooser(intent, "Compartilhar com"))
    }
}

class AcaoLembrete(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "lembrete"
    override val descricao = "Guarda lembrete no celular e sincroniza com PC quando conectado."
    override val parametros = esquema("quando", "texto")
    override suspend fun executar(argumentos: JsonObject): String {
        val quando = DatasPortugues.interpretar(argumentos.texto("quando"))
        val texto = argumentos.texto("texto").also { require(it.isNotBlank()) }
        ambiente.lembretes.adicionar(quando, texto)
        return "Lembrete guardado para sincronizar com o PC."
    }
}

class ListarLembretes(ambiente: AmbienteAcoes) : AcaoIntent(ambiente) {
    override val nome = "listar_lembretes"
    override val descricao = "Lista lembretes locais e a última cópia sincronizada do PC, incluindo feitos."
    override val parametros = esquema()
    override suspend fun executar(argumentos: JsonObject) = ambiente.lembretes.listar()
}

fun acoesCelular(ambiente: AmbienteAcoes) = RegistroAcoes(listOf(AbrirApp(ambiente), LerAgenda(ambiente), CriarEvento(ambiente), AlarmeTimer(ambiente), AbrirMapa(ambiente), PrepararMensagem(ambiente), Compartilhar(ambiente), AcaoLembrete(ambiente), ListarLembretes(ambiente), OperarTela()))
