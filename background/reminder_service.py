import time
import argparse
from features.notifications import ReminderNotifier

class DummyApp: 
    pass

def main(poll_seconds=60):
    notifier = ReminderNotifier(DummyApp(), poll_seconds=poll_seconds)
    notifier.start()
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        notifier.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=60, help="Số giây mỗi lần kiểm tra (poll_seconds)")
    args = parser.parse_args()
    main(poll_seconds=args.interval)