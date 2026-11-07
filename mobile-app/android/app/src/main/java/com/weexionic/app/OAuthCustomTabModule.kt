package com.weexionic.app

import android.content.Intent
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class OAuthCustomTabModule(reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

  override fun getName(): String = "OAuthCustomTab"

  @ReactMethod
  fun open(url: String, promise: Promise) {
    try {
      val uri = Uri.parse(url)
      val activity = currentActivity
      val customTabsIntent = CustomTabsIntent.Builder()
          .setShowTitle(true)
          .build()
      if (activity != null) {
        customTabsIntent.launchUrl(activity, uri)
      } else {
        customTabsIntent.intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        reactApplicationContext.startActivity(customTabsIntent.intent)
      }
      promise.resolve(true)
    } catch (e: Exception) {
      try {
        val fallback = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
          addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        reactApplicationContext.startActivity(fallback)
        promise.resolve(true)
      } catch (inner: Exception) {
        promise.reject("OAUTH_OPEN_FAILED", inner.message, inner)
      }
    }
  }
}

