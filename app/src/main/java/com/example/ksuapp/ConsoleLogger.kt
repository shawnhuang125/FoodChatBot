package com.example.ksuapp

import android.util.Log

object AppLog {

    private const val MAIN_TAG = "Logs"

    fun i(msg: String, module: String? = null) {
        Log.i(formatTag(module), msg)
    }

    fun w(msg: String, module: String? = null) {
        Log.w(formatTag(module), msg)
    }

    fun e(msg: String, throwable: Throwable? = null, module: String? = null) {
        if (throwable != null) {
            Log.e(formatTag(module), msg, throwable)
        } else {
            Log.e(formatTag(module), msg)
        }
    }

    private fun formatTag(module: String?): String {
        return if (module == null) MAIN_TAG else "${MAIN_TAG}_$module"
    }
}
