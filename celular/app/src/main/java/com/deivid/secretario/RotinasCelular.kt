package com.deivid.secretario

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.CalendarContract
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.*
import kotlinx.coroutines.CancellationException
import java.time.*
import java.time.temporal.TemporalAdjusters
import java.util.concurrent.TimeUnit

class RotinasCelular(private val contexto: Context, private val dados: DadosAprendizados) {
    suspend fun registrarAgenda() {
        val agora = LocalDateTime.now()
        dados.guardar(AprendizadoLocal("uso:${java.util.UUID.randomUUID()}", "agenda|$agora"))
    }
    suspend fun sugerir(confirmar: suspend (String) -> Boolean, permitir: suspend (List<String>) -> Boolean) {
        val usos = dados.listar("uso:%").mapNotNull { item -> runCatching {
            val partes = item.conteudo.split('|')
            UsoRotina(partes[0], LocalDateTime.parse(partes[1]))
        }.getOrNull() }
        val padrao = PadroesRotina.detectar(usos).firstOrNull { dados.ler(it.chave) == null } ?: return
        val dia = padrao.dia.getDisplayName(java.time.format.TextStyle.FULL, java.util.Locale.forLanguageTag("pt-BR"))
        val sim = confirmar("Você costuma pedir a agenda às ${padrao.hora}h de $dia. Quer receber a agenda nesse horário toda semana?")
        dados.guardar(AprendizadoLocal(padrao.chave, if (sim) "aprovada" else "recusada"))
        if (!sim) return
        val permissoes = mutableListOf(Manifest.permission.READ_CALENDAR)
        if (Build.VERSION.SDK_INT >= 33) permissoes.add(Manifest.permission.POST_NOTIFICATIONS)
        if (!permitir(permissoes)) {
            dados.guardar(AprendizadoLocal(padrao.chave, "sem_permissao")); return
        }
        val agora = ZonedDateTime.now()
        var proxima = agora.with(TemporalAdjusters.nextOrSame(padrao.dia)).withHour(padrao.hora).withMinute(0).withSecond(0).withNano(0)
        if (!proxima.isAfter(agora)) proxima = proxima.plusWeeks(1)
        val trabalho = PeriodicWorkRequestBuilder<RotinaAgendaWorker>(7, TimeUnit.DAYS)
            .setInitialDelay(Duration.between(agora, proxima).toMillis(), TimeUnit.MILLISECONDS).build()
        WorkManager.getInstance(contexto).enqueueUniquePeriodicWork(padrao.chave, ExistingPeriodicWorkPolicy.KEEP, trabalho)
    }
}

/** Rotina consentida de leitura local; não inicia automação nem ações finais. */
class RotinaAgendaWorker(contexto: Context, parametros: WorkerParameters) : CoroutineWorker(contexto, parametros) {
    override suspend fun doWork(): Result {
        if (ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED)
            return Result.failure()
        val banco = Banco.abrir(applicationContext)
        return try {
            val inicio = LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
            val fim = LocalDate.now().plusDays(1).atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
            val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().appendPath(inicio.toString()).appendPath(fim.toString()).build()
            val eventos = mutableListOf<String>()
            applicationContext.contentResolver.query(uri, arrayOf(CalendarContract.Instances.TITLE), null, null,
                CalendarContract.Instances.BEGIN + " ASC")?.use { cursor ->
                while (cursor.moveToNext() && eventos.size < 30) eventos.add(cursor.getString(0).orEmpty().take(200))
            }
            val texto = "Agenda de hoje: " + eventos.joinToString("; ").ifBlank { "sem eventos" }
            banco.dados().inserir(MensagemLocal(autor = "Secretário", texto = texto, origem = "Rotina"))
            val gerente = applicationContext.getSystemService(NotificationManager::class.java)
            gerente.createNotificationChannel(NotificationChannel("rotinas", "Rotinas aprovadas", NotificationManager.IMPORTANCE_DEFAULT))
            if (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(applicationContext,
                    Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                val abrir = PendingIntent.getActivity(applicationContext, 7, Intent(applicationContext, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
                gerente.notify(7, NotificationCompat.Builder(applicationContext, "rotinas").setSmallIcon(com.deivid.secretario.R.drawable.ic_secretario)
                    .setContentTitle("Agenda de hoje").setContentText("Sua agenda está na conversa").setContentIntent(abrir).setAutoCancel(true).build())
            }
            Result.success()
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { Result.failure() }
        finally { banco.close() }
    }
}
