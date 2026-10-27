package com.deivid.secretario

import org.junit.Assert.*
import org.junit.Test

class AtualizacaoTest {
    @Test fun comparaCodigoNumerico() {
        assertTrue(VerificacaoApk.maisNova(9, 10))
        assertFalse(VerificacaoApk.maisNova(10, 10))
        assertFalse(VerificacaoApk.maisNova(10, 9))
        assertTrue(VerificacaoApk.maisNova(1, Int.MAX_VALUE.toLong()))
    }

    @Test fun confereConteudoERejeitaAdulteracao() {
        val hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assertTrue("abc".byteInputStream().use { VerificacaoApk.conferir(it, hash) })
        assertTrue("abc".byteInputStream().use { VerificacaoApk.conferir(it, hash.uppercase()) })
        assertFalse("abd".byteInputStream().use { VerificacaoApk.conferir(it, hash) })
        assertFalse("abc".byteInputStream().use { VerificacaoApk.conferir(it, "inválido") })
        assertTrue(byteArrayOf().inputStream().use { VerificacaoApk.conferir(it,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855") })
    }
}
