package com.weexionic.app

import android.app.Activity
import android.content.Intent
import android.os.Bundle

class OAuthRedirectActivity : Activity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    val forward = Intent(this, MainActivity::class.java).apply {
      action = Intent.ACTION_VIEW
      data = intent?.data
      addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }
    startActivity(forward)
    finish()
  }
}

