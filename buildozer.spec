[app]
title = HS_23VT
package.name = hs23vt
package.domain = org.example
source.dir = .
source.include_exts = py,kv,png,xml,jpg,ini,json,ttf,otf,mp3,wav

version = 1.0.0

requirements = python3,kivy,kivymd,plyer,hostpython3,openssl,requests,urllib3,pyjnius,python-dotenv

orientation = portrait
fullscreen = 0

android.api = 33
android.minapi = 24
android.permissions = POST_NOTIFICATIONS,WAKE_LOCK,RECEIVE_BOOT_COMPLETED,FOREGROUND_SERVICE,INTERNET,VIBRATE

services = reminder:features/android_service.py

[buildozer]
log_level = 2
warn_on_root = 0
