import os, random
from kivy.core.audio import SoundLoader

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
        print(f"Looping: {os.path.basename(path)}")

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