requirements = python3,kivy,kivymd,plyer,hostpython3,openssl,requests,urllib3,pyjnius
android.api = 33
android.minapi = 24
android.permissions = POST_NOTIFICATIONS,WAKE_LOCK,RECEIVE_BOOT_COMPLETED,FOREGROUND_SERVICE,INTERNET
# Nếu bạn muốn dùng báo thức chính xác:
# android.permissions = ...,SCHEDULE_EXACT_ALARM
# (Android 12+ cần người dùng bật trong Settings; bạn có thể dẫn họ tới màn hình đó)
services = reminder:features/android_service.py
