# service_reminder.py (Android service)
import time
from features.notifications import ReminderNotifier

class DummyApp: pass

def main():
    notifier = ReminderNotifier(DummyApp(), poll_seconds=30)
    notifier.start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        notifier.stop()

if __name__ == "__main__":
    main()
