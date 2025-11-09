from kivy.utils import platform
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
import datetime
import os
import random

# ===== Windows AppID for Toast =====
if platform == "win":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HS_23VT")
    except Exception:
        pass


def _ensure_android_channel(activity, channel_id, channel_name="Reminders", importance_level=3):
    """
    Tạo NotificationChannel trên Android 8+ nếu chưa có.
    importance_level: 1=MIN, 2=LOW, 3=DEFAULT, 4=HIGH, 5=MAX (mapping gần đúng)
    """
    try:
        from jnius import autoclass
        Build_Version = autoclass('android.os.Build$VERSION')
        if Build_Version.SDK_INT < 26:
            return

        NotificationChannel = autoclass('android.app.NotificationChannel')
        NotificationManager = autoclass('android.app.NotificationManager')
        Context = autoclass('android.content.Context')

        nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
        importance = 4 if importance_level >= 4 else 3
        channel = NotificationChannel(channel_id, channel_name, importance)
        nm.createNotificationChannel(channel)
    except Exception as _:
        pass


def notify_system(title: str, message: str, nid: int = 1001):
    """Gửi system notification: Android → native; desktop → plyer."""
    if platform == "android":
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            activity = PythonActivity.mActivity
            NotificationCompat = autoclass('androidx.core.app.NotificationCompat')
            NotificationManagerCompat = autoclass('androidx.core.app.NotificationManagerCompat')
            PendingIntent = autoclass('android.app.PendingIntent')
            Intent = autoclass('android.content.Intent')

            CHANNEL_ID = 'hs23vt.reminders'
            _ensure_android_channel(activity, CHANNEL_ID, "HS_23VT Reminders", importance_level=4)

            intent = Intent(activity, PythonActivity)
            intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            pending = PendingIntent.getActivity(
                activity, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
            )

            builder = (
                NotificationCompat.Builder(activity, CHANNEL_ID)
                .setSmallIcon(activity.getApplicationInfo().icon)
                .setContentTitle(title)
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(True)
                .setContentIntent(pending)
            )

            nm = getattr(NotificationManagerCompat, "from")(activity)
            nm.notify(nid, builder.build())
            return True
        except Exception as e:
            print("Android native noti err:", e)

    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="HS_23VT",
            timeout=5,
        )
        return True
    except Exception as e:
        print("Plyer noti err:", e)
        return False


# ===== Music Player (Kivy SoundLoader loop) =====
class StudyMusicPlayer:
    AUDIO_EXTS = (".mp3", ".ogg", ".wav", ".m4a")

    def __init__(self):
        self.sound = None
        self.current_track = None
        self._last_volume = 0.6
        self.paused = False

    def play(self, folder="assets/sounds", volume=0.6):
        if self.sound:
            if self.paused:
                return self.resume()
            if getattr(self.sound, "state", "") == "play":
                return

        path = self._pick_random_track(folder)
        if not path:
            return

        snd = SoundLoader.load(path)
        if not snd:
            print(f"Không load được file: {path}")
            return

        for attr, val in (("loop", True), ("volume", volume)):
            try:
                setattr(snd, attr, val)
            except Exception:
                pass

        try:
            snd.play()
        except Exception as e:
            print("Sound play err:", e)
            try:
                snd.stop()
            except Exception:
                pass
            return

        self._last_volume = volume
        self.sound = snd
        self.current_track = path
        self.paused = False
        print(f"🎵 Looping: {os.path.basename(path)}")

    def pause(self):
        if not self.sound:
            return
        if hasattr(self.sound, "pause"):
            try:
                self.sound.pause()
            except Exception:
                self._safe_set_volume(0.0)
        else:
            self._safe_set_volume(0.0)
        self.paused = True

    def resume(self):
        if not self.sound:
            return self.play()
        try:
            self.sound.play()
        except Exception:
            pass
        self._safe_set_volume(getattr(self, "_last_volume", 0.6))
        self.paused = False

    def stop(self):
        if self.sound:
            try:
                self.sound.stop()
            except Exception:
                pass
            if hasattr(self.sound, "unload"):
                try:
                    self.sound.unload()
                except Exception:
                    pass
        self.sound = None
        self.current_track = None
        self.paused = False

    def set_volume(self, v: float):
        v = max(0.0, min(1.0, float(v)))
        self._last_volume = v
        self._safe_set_volume(v)

    def next_track(self, folder="assets/sounds"):
        vol = getattr(self, "_last_volume", 0.6)
        was_paused = self.paused

        if self.sound:
            try:
                self.sound.stop()
            except Exception:
                pass
            if hasattr(self.sound, "unload"):
                try:
                    self.sound.unload()
                except Exception:
                    pass
            self.sound = None

        path = self._pick_random_track(folder, prefer_different=True)
        if not path:
            return

        snd = SoundLoader.load(path)
        if not snd:
            print(f"Không load được file: {path}")
            return

        for attr, val in (("loop", True), ("volume", vol)):
            try:
                setattr(snd, attr, val)
            except Exception:
                pass

        try:
            snd.play()
        except Exception as e:
            print("Sound play err:", e)
            try:
                snd.stop()
            except Exception:
                pass
            return

        self.sound = snd
        self.current_track = path
        self.paused = False
        if was_paused:
            self.pause()

        print(f"Next: {os.path.basename(path)}")

    def is_playing(self) -> bool:
        if not self.sound:
            return False
        return (getattr(self.sound, "state", "") == "play") and (not self.paused)

    def current_track_name(self) -> str:
        return os.path.basename(self.current_track) if self.current_track else ""

    # ----- internals -----
    def _asset_dir(self, folder: str):
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.normpath(os.path.join(here, "..", folder)),
            os.path.normpath(os.path.join(here, folder)),
            os.path.normpath(folder),
        ]
        for p in candidates:
            if os.path.isdir(p):
                return p
        return None

    def _list_audio_files(self, root: str):
        try:
            return [
                os.path.join(root, f)
                for f in os.listdir(root)
                if f.lower().endswith(self.AUDIO_EXTS)
            ]
        except Exception as e:
            print("Lỗi đọc thư mục nhạc:", e)
            return []

    def _pick_random_track(self, folder: str, prefer_different: bool = True):
        root = self._asset_dir(folder)
        if not root:
            print(f"Thư mục nhạc không tồn tại: {folder}")
            return None

        files = self._list_audio_files(root)
        if not files:
            print(f"Không tìm thấy file nhạc trong: {root}")
            return None

        pool = files
        if prefer_different and self.current_track in files and len(files) > 1:
            pool = [f for f in files if f != self.current_track]
        return random.choice(pool)

    def _safe_set_volume(self, v: float):
        if not self.sound:
            return
        try:
            self.sound.volume = v
        except Exception:
            pass


# ===== Timetable Notifier =====
class ReminderNotifier:
    """
    Tick mỗi 60s:
      - Đến giờ 'time' của Timetable hôm nay → phát nhạc loop + noti
      - Đến 'end' → dừng nhạc + noti hết giờ
    Chống lặp theo phút.
    """
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

    # ----- Timetable -----
    def check_timetable_start_minute(self):
        """Đến giờ bắt đầu → phát nhạc (loop), lưu session, gửi noti."""
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
        """Đến giờ kết thúc của phiên đang active → dừng nhạc + noti “hết giờ”."""
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