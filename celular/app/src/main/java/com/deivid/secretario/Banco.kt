package com.deivid.secretario

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "mensagens")
data class MensagemLocal(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val autor: String,
    val texto: String,
    val origem: String,
    val instante: Long = System.currentTimeMillis()
)

@Entity(tableName = "fatos_pendentes")
data class FatoPendente(@PrimaryKey(autoGenerate = true) val id: Long = 0, val texto: String)

@Dao
interface Dados {
    @Query("SELECT * FROM mensagens ORDER BY id") fun mensagens(): Flow<List<MensagemLocal>>
    @Query("SELECT * FROM mensagens ORDER BY id DESC LIMIT 20") suspend fun recentes(): List<MensagemLocal>
    @Insert suspend fun inserir(mensagem: MensagemLocal)
    @Insert suspend fun aprender(fato: FatoPendente)
    @Query("SELECT * FROM fatos_pendentes ORDER BY id LIMIT 50") suspend fun fatos(): List<FatoPendente>
    @Query("SELECT COUNT(*) FROM fatos_pendentes") fun quantidadeFatos(): Flow<Int>
    @Query("DELETE FROM fatos_pendentes WHERE id IN (:ids)") suspend fun confirmar(ids: List<Long>)
}

@Database(entities = [MensagemLocal::class, FatoPendente::class], version = 1, exportSchema = true)
abstract class Banco : RoomDatabase() {
    abstract fun dados(): Dados
    companion object {
        fun abrir(contexto: Context): Banco = Room.databaseBuilder(contexto, Banco::class.java, "secretario.db").build()
    }
}
