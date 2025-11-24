import datetime
from kivy.clock import Clock
from .music_player import StudyMusicPlayer
from .system_notifier import notify_system

class ReminderNotifier:
    def __init__(self, app):
        self.app = app
        self._event = None
        self._fired_keys = set()
        self._fired_minute = None
        self.player = StudyMusicPlayer()
        self._active_sessions = {}

    def start(self):
        self._tick()
        self._event = Clock.schedule_interval(self._tick, 60)

    def stop(self):
        if self._event:
            self._event.cancel()
            self._event = None

    def _tick(self, *_):
        now_min = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        if self._fired_minute != now_min:
            self._fired_keys.clear()
            self._fired_minute = now_min

        if hasattr(self, "check_reminders_minute"):
            try:
                self.check_reminders_minute()
            except Exception as e:
                print("check_reminders_minute err:", e)

        self.check_timetable_start_minute()
        self.check_timetable_end_minute()

    def check_timetable_start_minute(self):
        try:
            from data.firebase_db import get_today_schedule
        except Exception as e:
            print("Import get_today_schedule err:", e)
            return

        now_hhmm = datetime.datetime.now().strftime("%H:%M")
        day_key, items = get_today_schedule()

        for it in (items or []):
            start = (it.get("time") or "").strip()
            if not start or start != now_hhmm:
                continue

            subj = (it.get("subject") or "Môn học").strip() or "Môn học"
            end = (it.get("end") or "").strip()
            unique_id = it.get("id") or f"{subj}|{start}"

            key = f"TT_START::{day_key}::{unique_id}::{start}"
            if key in self._fired_keys:
                continue
            self._fired_keys.add(key)

            if end:
                self._active_sessions[unique_id] = end

            title = f"{subj} ({start} - {end})" if end else f"{subj} ({start})"
            body = f"Đến giờ học {subj} rồi bạn ơi. Cùng ngồi vào bàn học nhé."
            notify_system(title, body)
            self.player.play()

            try:
                self.app.show_mini_player(title=title, playing=True)
            except Exception:
                pass

    def check_timetable_end_minute(self):
        if not self._active_sessions:
            return
        now_hhmm = datetime.datetime.now().strftime("%H:%M")
        to_remove = []
        for unique_id, end_hhmm in list(self._active_sessions.items()):
            if not end_hhmm:
                continue
            if end_hhmm == now_hhmm:
                key = f"TT_END::{unique_id}::{end_hhmm}"
                if key in self._fired_keys:
                    continue
                self._fired_keys.add(key)
                self.player.stop()
                notify_system("Hết giờ học rồi", "Giải lao một chút nhé.")
                try:
                    self.app.hide_mini_player()
                except Exception:
                    pass
                to_remove.append(unique_id)
        for uid in to_remove:
            self._active_sessions.pop(uid, None)