# background_notifier_windows.py
import time
from features.notifications import ReminderNotifier
# tạo "app giả" cho đúng signature, không dùng gì từ app cả
class DummyApp: pass

if __name__ == "__main__":
    print("[Notifier] start in background")
    notifier = ReminderNotifier(DummyApp(), poll_seconds=20)
    notifier.start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        notifier.stop()
