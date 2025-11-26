import os
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

from kivy.config import Config
from kivy.utils import platform
from kivymd.uix.snackbar import MDSnackbar, MDSnackbarText
from features.notifications import ReminderNotifier, notify_system
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import StringProperty
from kivy.factory import Factory
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivymd.app import MDApp
from kivymd.uix.dialog import (MDDialog, MDDialogContentContainer, MDDialogButtonContainer)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
from kivymd.uix.textfield import MDTextField
from kivymd.uix.pickers import MDTimePickerDialVertical
from kivymd.uix.label import MDLabel
from kivymd.uix.fitimage import FitImage
from data.firebase_db import (add_class_fb, get_schedule_by_day, delete_class_fb, update_class_fb, get_today_schedule)
from utils.days import normalize_day
from utils.constants import DAY_LABEL, DAY_ORDER
from utils.validators import is_valid_time, to_int
from data.services.firebase_auth import sign_in_anonymous
from app_state import set_uid
from features.notes import NoteManager
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from typing import Optional
from features.notes import Note

# ============================== CẤU HÌNH CỬA SỔ & BÀN PHÍM ==============================
Config.set('graphics', 'width', '411')
Config.set('graphics', 'height', '846')
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'borderless', '1')
Config.set('kivy', 'exit_on_escape', '1')
Config.set('kivy', 'keyboard_mode', 'system')
Config.set('kivy', 'keyboard', 'system')
if platform in ("win", "linux", "macosx"):
    Config.set('graphics', 'borderless', '0')
Config.write()

# ============================== ỨNG DỤNG CHÍNH (MDApp) ==============================
class HS23VTApp(MDApp):
    current_section = StringProperty("timetable")
    DAY_OPTIONS = [(DAY_LABEL[k], k) for k in DAY_ORDER]

    def _label_for(self, key: str) -> str:
        return DAY_LABEL.get(key, "Th2")

    # ------------------------------ Lấy chiều cao status bar (Android) ------------------------------
    def _android_statusbar_dp(self) -> float:
        if platform != "android":
            return 0.0
        from jnius import autoclass

        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        res = activity.getResources()
        dm = res.getDisplayMetrics()
        density = dm.density if dm and dm.density else 1.0
        rid = res.getIdentifier('status_bar_height', 'dimen', 'android')
        px = res.getDimensionPixelSize(rid) if rid > 0 else 0

        return px / density

    # ------------------------------ Khởi tạo giao diện (build) ------------------------------
    def build(self):
        self.title = "HS_23VT"
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        self.theme_cls.material_style = "M3"
        self.bg_color        = (0.90, 0.96, 0.95, 1)
        self.surface_color   = (0.88, 0.95, 0.94, 1)
        self.surface_low     = (0.92, 0.97, 0.96, 1)
        self.on_surface      = (0.15, 0.25, 0.24, 1)
        self.search_bg       = (0.27, 0.25, 0.26, 1)
        self.search_hint     = (1, 1, 1, 0.8)
        self.icon_muted      = (1, 0.9, 0.93, 0.9)
        self.primary_teal    = (0.39, 0.74, 0.67, 1)
        self.drawer_bg       = (0.22, 0.50, 0.46, 1)
        self.status_bar_height = dp(28)

        if platform == "android":
            try:
                sb_dp = self._android_statusbar_dp()
                self.status_bar_height = sb_dp
            except Exception:
                pass

        self.avatar_src = os.path.join(os.path.dirname(__file__), "assets", "avatar.jpg")

        Window.softinput_mode = "below_target"
        kv_path = os.path.join(os.path.dirname(__file__), "ui", "hs23vt.kv")
        root = Builder.load_file(kv_path)

        self.screen = root

        return root

    # ------------------------------ Thông báo ngắn (Toast/Snackbar) ------------------------------
    def show_message(self, text: str, delay: float = 0.20):
        def _open(*_):
            try:
                if platform == "android":
                    from kivymd.toast import toast
                    toast(text)
                else:
                    bar = MDSnackbar(
                        MDSnackbarText(
                            text=text,
                            theme_text_color="Custom",
                            text_color=(1, 1, 1, 1),
                        ),
                        pos_hint={"center_x": 0.5, "y": 0.05},
                        size_hint_x=0.92,
                        duration=2.2,
                    )
                    bar.theme_bg_color = "Custom"
                    bar.md_bg_color = (0.39, 0.74, 0.67, 1)
                    bar.open()
            except Exception as e:
                print("Message:", text, "| err:", e)

        from kivy.clock import Clock
        Clock.schedule_once(_open, delay)

    # ------------------------------ Vòng đời: on_start / on_stop ------------------------------
    def on_start(self):
        ids = self.root.ids
        sm = self.root.ids.sm
        sm.bind(current=lambda *_: self._update_fab_visibility())

        # tham chiếu widget timetable
        self.morning_list    = ids.morning_list
        self.afternoon_list  = ids.afternoon_list
        self.morning_title   = ids.morning_title
        self.afternoon_title = ids.afternoon_title
        self._section_before_search = None

        # init notes manager
        try:
            self.note_manager = NoteManager()
        except Exception as e:
            # print("NoteManager init err:", e)
            self.note_manager = None

        # cache reminder trong RAM
        self._note_reminders = {}

        # schedule lại các nhắc việc còn hạn trong DB
        try:
            self._reschedule_note_reminders_on_start()
        except Exception as e:
            print("reschedule note reminders on_start err:", e)

        # Notifier (phục vụ phát âm / thông báo liên quan UI hiện tại)
        self.notifier = ReminderNotifier(self)
        self.notifier.start()

        # Cấp quyền & tạo kênh thông báo (Android 8+)
        self._ensure_notification_permission()
        self._ensure_notification_channel()

        # Lấy lịch hôm nay & hiển thị
        today_key, _ = get_today_schedule()
        self.current_day = today_key
        self.load_timetable(today_key)

        # (tuỳ chọn) refresh notes nếu có UI notes
        try:
            self._update_search_ui()
        except Exception:
            pass

    def on_stop(self):
        if hasattr(self, "notifier"):
            self.notifier.stop()

    # ------------------------------ Label hiển thị cho ngày ------------------------------
    def label_for_day(self, day_key: str) -> str:
        return DAY_LABEL.get(day_key, "Th2")

    # ------------------------------ Tải & hiển thị Thời khóa biểu theo ngày ------------------------------
    def load_timetable(self, day_key: str):
        self.current_day = normalize_day(day_key)
        self._highlight_day_chip(self.current_day)
        self.morning_list.clear_widgets()
        self.afternoon_list.clear_widgets()

        items = get_schedule_by_day(self.current_day) or []

        def _safe_min(hhmm: str) -> int:
            m = self._hhmm_to_min(hhmm or "00:00")
            return m if m is not None else 99999

        items.sort(key=lambda it: _safe_min(it.get("time", "00:00")))

        cnt_s, cnt_c = 0, 0

        for it in items:
            card = Factory.TimetableItem()
            card.subject  = it.get('subject','?')
            card.time_str = it.get('time','--:--')
            card.end_str  = it.get('end','--:--')
            card.period   = str(it.get('period','?'))
            class_id = it.get("id")
            card.on_release = (lambda _rid=class_id, _day=self.current_day:
                               self.show_edit_class_dialog(_day, _rid))

            if self._is_morning(card.time_str):
                self.morning_list.add_widget(card)
                cnt_s += 1
            else:
                self.afternoon_list.add_widget(card)
                cnt_c += 1

        self.morning_title.height   = dp(28) if cnt_s else 0
        self.morning_title.opacity  = 1 if cnt_s else 0
        self.afternoon_title.height = dp(28) if cnt_c else 0
        self.afternoon_title.opacity= 1 if cnt_c else 0

        empty = self.screen.ids.get("empty_tt_label")

        if empty:
            has_items = (cnt_s + cnt_c) > 0
            empty.opacity = 0 if has_items else 1
            empty.height  = 0 if has_items else dp(28)

    # ------------------------------ Nút “Hôm nay” ------------------------------
    def view_today(self):
        day, _ = get_today_schedule()
        self.load_timetable(day)

    # ------------------------------ Dialog: Thêm tiết học ------------------------------
    def show_add_class_dialog(self):
        TITLE_H     = 26
        FIELD_H     = 40
        PAD_X       = 16
        PAD_TOP     = 6
        PAD_BOT     = 0
        FORM_SP     = 10
        BTN_H       = 40
        BTN_SP      = 12
        DIALOG_W    = 0.96
        DIALOG_MAXH = 520
        EXTRA_H     = 110
        TEAL = (0.39, 0.74, 0.67, 1)
        TEAL_PRESSED = (0.33, 0.63, 0.57, 1)

        def lbl(text, required=False):
            if required:
                return MDLabel(
                    text=f"{text} [color=#FF3B30](*)[/color]",
                    markup=True,
                    theme_text_color="Secondary",
                    font_size="16sp",
                    size_hint_y=None,
                    height="22dp",
                )

            return MDLabel(
                text=text,
                theme_text_color="Secondary",
                font_size="16sp",
                size_hint_y=None,
                height="22dp",
            )

        form = BoxLayout(
            orientation="vertical",
            spacing=dp(FORM_SP),
            padding=[dp(PAD_X), 0, dp(PAD_X), 0],
            size_hint_y=None,
        )
        form.bind(minimum_height=form.setter("height"))

        title = MDLabel(
            text="Thêm tiết học", halign="center", bold=True,
            font_size="20sp", size_hint_y=None, height=dp(TITLE_H)
        )

        def lbl(text, required=False):
            if required:
                return MDLabel(
                    text=f"{text} [color=#FF3B30](*)[/color]",
                    markup=True,
                    theme_text_color="Secondary",
                    font_size="16sp",
                    size_hint_y=None,
                    height=dp(22),
                )
            return MDLabel(
                text=text,
                theme_text_color="Secondary",
                font_size="16sp",
                size_hint_y=None,
                height=dp(22),
            )

        field_kwargs = dict(mode="outlined", size_hint_y=None, height=dp(FIELD_H), size_hint_x=1)

        self.tk_subj   = MDTextField(**field_kwargs)
        self.tk_time   = MDTextField(hint_text="Chọn giờ bắt đầu", readonly=True, **field_kwargs)
        self.tk_end    = MDTextField(hint_text="Chọn giờ kết thúc", readonly=True, **field_kwargs)
        self.tk_day_key   = self.current_day
        self.tk_day_field = MDTextField(text=self._label_for(self.tk_day_key), readonly=True, **field_kwargs)

        form.add_widget(title)
        form.add_widget(lbl("Môn học", required=True))
        form.add_widget(self.tk_subj)

        form.add_widget(lbl("Giờ bắt đầu", required=True))
        form.add_widget(self.tk_time)

        form.add_widget(lbl("Giờ kết thúc", required=True))
        form.add_widget(self.tk_end)

        form.add_widget(lbl("Thứ", required=True))
        form.add_widget(self.tk_day_field)

        self.tk_time.bind(on_touch_down=lambda w, t: self._open_time_if_hit(w, t))
        self.tk_end.bind(on_touch_down=lambda w, t: self._open_time_if_hit(w, t))
        self.tk_day_menu = self._build_day_menu(self.tk_day_field, self._set_add_day_from_menu)
        self.tk_day_field.bind(on_touch_down=lambda w, t: self._open_menu_if_hit(w, t, self.tk_day_menu))

        btn_huy = MDButton(
            MDButtonText(
                text="HỦY",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            size_hint=(None, None),
            height=dp(BTN_H),
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self.tk_add_dialog.dismiss()),
        )

        btn_luu = MDButton(
            MDButtonText(
                text="LƯU",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            size_hint=(None, None),
            height=dp(BTN_H),
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self._save_new_class()),
        )

        content = MDDialogContentContainer(
            form,
            size_hint_y=None,
            height=form.height,
            padding=[dp(PAD_X), dp(PAD_TOP), dp(PAD_X), dp(PAD_BOT)],
        )

        self.tk_add_dialog = MDDialog(
            content,
            MDDialogButtonContainer(
                Widget(),
                btn_huy,
                btn_luu,
                spacing=f"{BTN_SP}px",
                padding=[dp(PAD_X), 0, dp(PAD_X), dp(PAD_X)],
            ),
        )

        self.tk_add_dialog.size_hint = (DIALOG_W, None)
        self.tk_add_dialog.theme_bg_color = "Custom"
        self.tk_add_dialog.md_bg_color = (0.898, 0.961, 0.949, 1)
        self.tk_add_dialog.radius = [dp(24)]

        def _autofit(*_):
            content.height = form.height
            self.tk_add_dialog.height = min(dp(DIALOG_MAXH), content.height + dp(EXTRA_H))
        Clock.schedule_once(_autofit, 0)

        self.tk_add_dialog.open()

    # ------------------------------ Lưu tiết học mới ------------------------------
    def _save_new_class(self, *_):
        subj = (self.tk_subj.text or "").strip()
        time_str = (self.tk_time.text or "").strip()
        end_str  = (self.tk_end.text or "").strip()
        day_text = normalize_day(self.tk_day_key or self.current_day)

        if not subj or not day_text:
            self.show_message("Vui lòng nhập đủ thông tin.")
            return
        if not time_str or not end_str:
            self.show_message("Vui lòng nhập đủ thông tin.")
            return
        if not is_valid_time(time_str) or not is_valid_time(end_str):
            self.show_message("Định dạng giờ không hợp lệ (cần hh:mm).")
            return

        s = self._hhmm_to_min(time_str)
        e = self._hhmm_to_min(end_str)
        if s is None or e is None:
            self.show_message("Định dạng giờ không hợp lệ (cần hh:mm).")
            return
        if e <= s:
            self.show_message("Giờ kết thúc phải lớn hơn giờ bắt đầu.")
            return

        has_conflict, rec = self._has_conflict_on_day(day_text, s, e)
        if has_conflict:
            other_subj = rec.get("subject", "môn khác")
            other_t = f"{rec.get('time','--:--')}–{rec.get('end','--:--')}"
            self.show_message(f"Đã tồn tại {other_subj} ({other_t}).")
            return

        add_class_fb(subj, 0, time_str, end_str, day_text)
        self.tk_add_dialog.dismiss()
        self.load_timetable(day_text)
        self.show_message("Đã thêm tiết học.")

    # ------------------------------ Dialog: Sửa/Xóa tiết học ------------------------------
    def show_edit_class_dialog(self, day_text: str, class_id: str):
        items = get_schedule_by_day(day_text)
        rec = next((x for x in items if x.get("id") == class_id), None)
        if not rec:
            return

        TITLE_H = 26
        FIELD_H = 40
        PAD_X = 16
        PAD_TOP = 6
        PAD_BOT = 0
        FORM_SP = 10
        BTN_H = 40
        BTN_SP = 12
        DIALOG_W = 0.96
        DIALOG_MAXH = 520
        EXTRA_H = 110
        TEAL = (0.39, 0.74, 0.67, 1)
        TEAL_PRESSED = (0.33, 0.63, 0.57, 1)

        def lbl(text, required=False):
            if required:
                return MDLabel(
                    text=f"{text} [color=#FF3B30](*)[/color]",
                    markup=True,
                    theme_text_color="Secondary",
                    font_size="16sp",
                    size_hint_y=None,
                    height="22dp",
                )
            return MDLabel(
                text=text,
                theme_text_color="Secondary",
                font_size="16sp",
                size_hint_y=None,
                height="22dp",
            )

        form = BoxLayout(
            orientation="vertical",
            spacing=dp(FORM_SP),
            padding=[dp(PAD_X), 0, dp(PAD_X), 0],
            size_hint_y=None,
        )
        form.bind(minimum_height=form.setter("height"))

        title = MDLabel(
            text="Sửa/Xoá tiết học",
            halign="center",
            bold=True,
            font_size="20sp",
            size_hint_y=None,
            height=dp(TITLE_H),
        )
        form.add_widget(title)

        field_kwargs = dict(mode="outlined", size_hint_y=None, height=dp(FIELD_H), size_hint_x=1)

        form.add_widget(lbl("Môn học", required=True))
        self.ed_subj = MDTextField(text=rec.get("subject", ""), **field_kwargs)
        form.add_widget(self.ed_subj)

        form.add_widget(lbl("Giờ bắt đầu", required=True))
        self.ed_time = MDTextField(
            text=rec.get("time", ""), hint_text="Chọn giờ bắt đầu", readonly=True, **field_kwargs
        )
        form.add_widget(self.ed_time)

        form.add_widget(lbl("Giờ kết thúc", required=True))
        self.ed_end = MDTextField(
            text=rec.get("end", ""), hint_text="Chọn giờ kết thúc", readonly=True, **field_kwargs
        )
        form.add_widget(self.ed_end)

        form.add_widget(lbl("Thứ", required=True))
        self.ed_day_key = normalize_day(day_text)
        self.ed_day_field = MDTextField(
            text=self._label_for(self.ed_day_key), readonly=True, **field_kwargs
        )
        form.add_widget(self.ed_day_field)

        self.ed_day_menu = self._build_day_menu(
            caller_widget=self.ed_day_field,
            set_fn=self._set_edit_day_from_menu,
        )
        self.ed_day_field.bind(on_touch_down=lambda w, t: (
            self._open_menu_if_hit(w, t, self.ed_day_menu)
        ))

        self.ed_time.bind(on_touch_down=lambda w, t: self._open_time_if_hit(w, t))
        self.ed_end.bind(on_touch_down=lambda w, t: self._open_time_if_hit(w, t))

        btn_delete = MDButton(
            MDButtonText(text="XOÁ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="elevated",
            size_hint=(None, None),
            height=dp(BTN_H),
            theme_bg_color="Custom",
            md_bg_color=(0.91, 0.33, 0.31, 1),
            on_press=lambda x: setattr(x, "md_bg_color", (0.78, 0.28, 0.26, 1)),
            on_release=lambda x: (
                setattr(x, "md_bg_color", (0.91, 0.33, 0.31, 1)),
                self._delete_class(day_text, class_id),
            ),
        )

        btn_cancel = MDButton(
            MDButtonText(text="HUỶ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="elevated",
            size_hint=(None, None),
            height=dp(BTN_H),
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self.tk_edit_dialog.dismiss()),
        )

        btn_save = MDButton(
            MDButtonText(text="LƯU", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="elevated",
            size_hint=(None, None),
            height=dp(BTN_H),
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self._update_class(day_text, class_id)),
        )

        content = MDDialogContentContainer(
            form,
            size_hint_y=None,
            height=form.height,
            padding=[dp(PAD_X), dp(PAD_TOP), dp(PAD_X), dp(PAD_BOT)],
        )

        self.tk_edit_dialog = MDDialog(
            content,
            MDDialogButtonContainer(
                btn_delete,
                Widget(),
                btn_cancel,
                btn_save,
                spacing=f"{BTN_SP}px",
                padding=[dp(PAD_X), 0, dp(PAD_X), dp(PAD_X)],
            ),
        )

        self.tk_edit_dialog.size_hint = (DIALOG_W, None)
        self.tk_edit_dialog.theme_bg_color = "Custom"
        self.tk_edit_dialog.md_bg_color = (0.898, 0.961, 0.949, 1)
        self.tk_edit_dialog.radius = [dp(24)]

        def _autofit(*_):
            content.height = form.height
            self.tk_edit_dialog.height = min(dp(DIALOG_MAXH), content.height + dp(EXTRA_H))
        Clock.schedule_once(_autofit, 0)

        self.tk_edit_dialog.open()

    # ------------------------------ Cập nhật tiết học ------------------------------
    def _update_class(self, old_day_text: str, class_id: str):
        subj = (self.ed_subj.text or "").strip()
        time_str = (self.ed_time.text or "").strip()
        end_str  = (self.ed_end.text or "").strip()
        new_day_text = normalize_day(self.ed_day_key or old_day_text)

        if not subj or not new_day_text:
            self.show_message("Vui lòng nhập đủ thông tin.")
            return
        if not time_str or not end_str:
            self.show_message("Vui lòng chọn cả Giờ bắt đầu và Giờ kết thúc.")
            return
        if not is_valid_time(time_str) or not is_valid_time(end_str):
            self.show_message("Định dạng giờ không hợp lệ (cần hh:mm).")
            return

        s = self._hhmm_to_min(time_str)
        e = self._hhmm_to_min(end_str)
        if s is None or e is None:
            self.show_message("Định dạng giờ không hợp lệ (cần hh:mm).")
            return
        if e <= s:
            self.show_message("Giờ kết thúc phải lớn hơn giờ bắt đầu.")
            return

        has_conflict, rec = self._has_conflict_on_day(new_day_text, s, e, exclude_id=class_id)
        if has_conflict:
            other_subj = rec.get("subject", "môn khác")
            other_t = f"{rec.get('time','--:--')}–{rec.get('end','--:--')}"
            self.show_message(f"Đã tồn tại {other_subj} ({other_t}).")
            return

        update_class_fb(
            class_id, old_day_text,
            subject=subj, period=0, time_str=time_str, end_str=end_str,
            new_day_text=new_day_text,
        )
        self.tk_edit_dialog.dismiss()
        self.load_timetable(new_day_text)
        self.show_message("Đã sửa tiết học.")

    # ------------------------------ Xóa tiết học (kèm dialog xác nhận) ------------------------------
    def _delete_class(self, day_text: str, class_id: str):
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer, MDDialogButtonContainer
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        from kivy.metrics import dp
        from kivy.core.window import Window
        from kivy.uix.widget import Widget

        TEAL = (0.39, 0.74, 0.67, 1)
        RED  = (0.91, 0.33, 0.31, 1)

        def _confirm_delete(*_):
            try:
                delete_class_fb(day_text, class_id)
                self.tk_edit_dialog.dismiss()
                self.load_timetable(normalize_day(day_text))
                self.show_message("Đã xoá tiết học.")
            except Exception as e:
                self.show_message("Lỗi khi xoá tiết học.")
                print("Delete error:", e)

        dialog_width = min(dp(460), Window.width * 0.95)

        msg = MDLabel(
            text="Bạn có chắc muốn xoá tiết học này không?",
            halign="center",
            theme_text_color="Custom",
            text_color=(0, 0, 0, 1),
            font_size="16sp",
            size_hint=(1, None),
            max_lines=1,
            shorten=True,
            shorten_from="right",
        )

        msg.text_size = (dialog_width - dp(48), None)
        msg.texture_update()
        msg.height = msg.texture_size[1]

        box = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=msg.height + dp(4),
            padding=[dp(12), dp(12), dp(12), dp(2)],
        )
        box.add_widget(msg)

        content = MDDialogContentContainer(
            box,
            padding=[0, 0, 0, 0],
            spacing=dp(0),
        )

        btn_cancel = MDButton(
            MDButtonText(text="HUỶ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="filled",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            radius=[dp(14)],
            size_hint=(None, None),
            height=dp(34),
            on_release=lambda *_: dialog.dismiss(),
        )
        btn_ok = MDButton(
            MDButtonText(text="XOÁ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="filled",
            theme_bg_color="Custom",
            md_bg_color=RED,
            radius=[dp(14)],
            size_hint=(None, None),
            height=dp(34),
            on_release=lambda *_: (_confirm_delete(), dialog.dismiss()),
        )

        dialog = MDDialog(
            content,
            MDDialogButtonContainer(
                Widget(),
                btn_cancel,
                btn_ok,
                Widget(),
                spacing="10dp",
                padding=[dp(8), dp(4), dp(8), dp(8)],
            ),
        )
        dialog.size_hint = (None, None)
        dialog.width = dialog_width
        dialog.height = dp(130)
        dialog.theme_bg_color = "Custom"
        dialog.md_bg_color = (1, 1, 1, 1)
        dialog.radius = [dp(16)]
        dialog.open()

    # ------------------------------ Drawer & Điều hướng ------------------------------
    def open_drawer(self, *args):
        self.screen.ids.nav_drawer.set_state("open")

    def close_drawer(self, *_):
        self.screen.ids.nav_drawer.set_state("close")

    def select_nav(self, name: str):
        self.current_section = name
        if name == "timetable":
            self.show_timetable()
        self.close_drawer()

    def show_timetable(self, *_):
        self.view_today()
        self.screen.ids.sm.current = "timetable"

    # ------------------------------ Tô sáng chip ngày đang chọn ------------------------------
    def _highlight_day_chip(self, day_key):
        ids = self.screen.ids
        mapping = {"monday":"chip_mon","tuesday":"chip_tue","wednesday":"chip_wed",
                   "thursday":"chip_thu","friday":"chip_fri","saturday":"chip_sat","sunday":"chip_sun"}
        for k, wid in mapping.items():
            chip = ids.get(wid)
            if chip:
                chip.active = (k == day_key)

    # ------------------------------ FAB: mở dialog thêm tiết học ------------------------------
    def on_center_fab(self, *_):
        """
        - Nếu đang ở màn 'notes' -> mở/đóng menu loại ghi chú (text/list/draw/image/audio).
        - Ngược lại: giữ hành vi hiện tại (thêm tiết học cho TKB).
        """
        try:
            current = self.root.ids.sm.current
        except Exception:
            current = None

        if current == "notes":
            self._toggle_note_fab_menu()
            return

        # Hành vi cũ cho timetable
        try:
            if hasattr(self, "show_add_class_dialog"):
                self.show_add_class_dialog()
        except Exception as e:
            print("FAB timetable err:", e)

    # ------------------------------ Điều hướng có hiệu ứng ripple ------------------------------
    def nav_after_ripple(self, name: str):
        self.current_section = name

        try:
            sm = getattr(self, "screen", None).ids.get("sm")
        except Exception:
            sm = None
        try:
            if sm and name in getattr(sm, "screen_names", []):
                sm.current = name
        except Exception:
            pass

        try:
            if name == "timetable":
                self.show_timetable()
            elif name == "notes":
                # khi mở Ghi chú thì làm mới danh sách + search UI
                try:
                    self._update_search_ui()
                except Exception:
                    pass
                try:
                    self.refresh_notes()      # 👈 THÊM DÒNG NÀY
                except Exception as e:
                    print("refresh_notes err:", e)
        except Exception:
            pass

        Clock.schedule_once(lambda *_: self.close_drawer(), 0.18)

    def nav_and_close(self, name: str):
        self.current_section = name
        try:
            sm = getattr(self, "screen", None).ids.get("sm")
        except Exception:
            sm = None
        try:
            if sm and name in getattr(sm, "screen_names", []):
                sm.current = name
        except Exception:
            pass

        try:
            if name == "timetable":
                self.show_timetable()
            elif name == "notes":
                try:
                    self.refresh_notes()
                except Exception:
                    pass
        except Exception:
            pass

        Clock.schedule_once(lambda *_: self.close_drawer(), 0)

    # ------------------------------ Phân loại buổi sáng/chiều ------------------------------
    def _is_morning(self, time_str: str) -> bool:
        try:
            hh = int((time_str or "00:00").split(":")[0])
            return hh < 12
        except Exception:
            return True

    # ------------------------------ Menu chọn Thứ ------------------------------
    def _build_day_menu(self, caller_widget, set_fn):
        items = []
        for label, key in self.DAY_OPTIONS:
            items.append({
                "text": label,
                "on_release": (lambda k=key, l=label: set_fn(k, l))
            })

        menu = MDDropdownMenu(
            caller=caller_widget,
            items=items,
            md_bg_color=(1, 1, 1, 1),
        )
        menu.width = dp(160)

        def _resize_menu(*_):
            if caller_widget.width:
                menu.width = caller_widget.width * 0.75
        Clock.schedule_once(_resize_menu, 0)

        def _reposition(*_):
            try:
                cx, cy = caller_widget.to_window(caller_widget.x, caller_widget.y)
                x = cx + caller_widget.width - menu.menu.width
                y = cy - menu.menu.height
                menu.menu.pos = (x, y)
            except Exception as e:
                print("reposition menu err:", e)
        menu.bind(on_open=lambda *_: Clock.schedule_once(_reposition, 0))

        return menu

    def _open_menu_if_hit(self, widget, touch, menu):
        if widget.collide_point(*touch.pos):
            menu.open()
        return False

    # ------------------------------ Time Picker (an toàn, tự chuyển phút) ------------------------------
    def _open_time_if_hit(self, widget, touch):
        if widget.collide_point(*touch.pos):
            self._open_time_picker(widget)
            return True
        return False

    def _open_time_picker(self, target_field):
        """Mở time picker an toàn, không vòng lặp, tự chuyển sang phút."""
        if hasattr(self, "_active_picker") and self._active_picker:
            try:
                self._active_picker.dismiss()
            except Exception:
                pass
            self._active_picker = None

        parent = None
        for name in ("tk_edit_dialog", "tk_add_dialog"):
            dlg = getattr(self, name, None)
            if dlg and getattr(dlg, "attached_to_window", False):
                parent = dlg
                try:
                    dlg.dismiss()
                except Exception:
                    pass
                break

        picker = MDTimePickerDialVertical()
        self._active_picker = picker

        def _force_switch_to_minute(*_):
            try:
                if hasattr(picker, "state") and picker.state == "hour":
                    picker.state = "minute"
            except Exception:
                pass

        def _cleanup_and_reopen(*_):
            if self._active_picker:
                try:
                    self._active_picker.dismiss()
                except Exception:
                    pass
            self._active_picker = None
            if parent:
                Clock.schedule_once(lambda *_: parent.open(), 0.1)

        def _on_ok(inst):
            self._set_time_field(target_field, getattr(inst, "time", None))
            _cleanup_and_reopen()

        def _on_cancel(inst):
            _cleanup_and_reopen()

        picker.bind(
            on_ok=_on_ok,
            on_cancel=_on_cancel,
            on_dismiss=lambda *_: setattr(self, "_active_picker", None),
            on_touch_up=_force_switch_to_minute
        )

        picker.open()

    def _set_time_field(self, field, time_obj):
        """Set HH:MM vào TextField sau khi chọn từ đồng hồ."""
        if not time_obj:
            return
        try:
            h = int(getattr(time_obj, "hour", 0))
            m = int(getattr(time_obj, "minute", 0))
            field.text = f"{h:02d}:{m:02d}"
        except Exception as e:
            print("Error setting time:", e)
        return

    # ------------------------------ Callback menu chọn Thứ ------------------------------
    def _set_add_day_from_menu(self, key, label):
        self.tk_day_key = key
        if getattr(self, "tk_day_field", None):
            self.tk_day_field.text = label
        if getattr(self, "tk_day_menu", None):
            self.tk_day_menu.dismiss()

    def _set_edit_day_from_menu(self, key, label):
        self.ed_day_key = key
        if getattr(self, "ed_day_field", None):
            self.ed_day_field.text = label
        if getattr(self, "ed_day_menu", None):
            self.ed_day_menu.dismiss()

    # ------------------------------ Quyền & Kênh thông báo (Android) ------------------------------
    def _ensure_notification_permission(self):
        if platform != "android":
            return
        from jnius import autoclass, cast
        Build = autoclass('android.os.Build')
        if Build.VERSION.SDK_INT < 33:
            return
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        ContextCompat = autoclass('androidx.core.content.ContextCompat')
        PackageManager = autoclass('android.content.pm.PackageManager')
        Manifest = autoclass('android.Manifest')
        if ContextCompat.checkSelfPermission(activity, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED:
            ActivityCompat = autoclass('androidx.core.app.ActivityCompat')
            ActivityCompat.requestPermissions(activity, [Manifest.permission.POST_NOTIFICATIONS], 1001)

    def _ensure_notification_channel(self):
        if platform != "android":
            return
        from jnius import autoclass, cast
        Build = autoclass('android.os.Build')
        if Build.VERSION.SDK_INT < 26:
            return
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        Context = autoclass('android.content.Context')
        NotificationManager = autoclass('android.app.NotificationManager')
        NotificationChannel = autoclass('android.app.NotificationChannel')

        channel_id = 'hs23vt.reminders'
        name = 'HS_23VT Reminders'
        importance = NotificationManager.IMPORTANCE_HIGH

        nm = cast(NotificationManager, activity.getSystemService(Context.NOTIFICATION_SERVICE))
        existing = nm.getNotificationChannel(channel_id)
        if existing is None:
            ch = NotificationChannel(channel_id, name, importance)
            ch.setDescription('Nhắc học & thời khóa biểu')
            nm.createNotificationChannel(ch)

    # ------------------------------ Mini Player: hiển thị & đồng bộ trạng thái ------------------------------
    def show_mini_player(self, title: str, subtitle: str = "", playing: bool = True):
        mp = self.root.ids.get("mini_player")
        if not mp:
            return
        mp.title_text = title
        mp.subtitle_text = subtitle or ""
        mp.playing = playing
        mp.disabled = False
        mp.opacity = 1
        mp.duration = self._get_duration()
        mp._has_duration = mp.duration > 0
        mp.position = self._get_position()

    def _format_time(self, secs):
        try:
            s = int(max(0, float(secs)))
            m, s = divmod(s, 60)
            return f"{m:02d}:{s:02d}"
        except Exception:
            return "00:00"

    def _get_duration(self):
        p = getattr(self.notifier, "player", None)
        if not p or not p.sound:
            return 0.0
        return float(getattr(p.sound, "length", 0.0) or 0.0)

    def _get_position(self):
        p = getattr(self.notifier, "player", None)
        if not p or not p.sound:
            return 0.0
        try:
            if hasattr(p.sound, "get_pos"):
                pos = p.sound.get_pos()
                return float(pos if pos is not None else 0.0)
        except Exception:
            pass
        return 0.0

    def _seek_to(self, seconds: float):
        p = getattr(self.notifier, "player", None)
        if not p or not p.sound:
            return
        try:
            if hasattr(p.sound, "seek"):
                p.sound.seek(max(0.0, float(seconds)))
        except Exception:
            pass

    def _tick_mini_player(self, *_):
        mp = self.root.ids.get("mini_player")
        if not mp:
            return
        if not getattr(mp, "_has_duration", False):
            dur = self._get_duration()
            if dur > 0:
                mp.duration = dur
                mp._has_duration = True
        mp.position = self._get_position()
        p = getattr(self.notifier, "player", None)
        if p and p.sound:
            try:
                v = float(getattr(p.sound, "volume", mp.volume))
                mp.volume = v
            except Exception:
                pass

    def _start_progress_timer(self):
        if hasattr(self, "_mp_event") and self._mp_event:
            return
        self._mp_event = Clock.schedule_interval(self._tick_mini_player, 0.5)

    def _stop_progress_timer(self):
        if getattr(self, "_mp_event", None):
            try:
                self._mp_event.cancel()
            except Exception:
                pass
        self._mp_event = None

    def update_mini_player_state(self, playing: bool):
        mp = self.root.ids.get("mini_player")
        if mp:
            mp.playing = playing

    def hide_mini_player(self):
        mp = self.root.ids.get("mini_player")
        if mp:
            mp.disabled = True
            mp.opacity = 0
        self._stop_progress_timer()

    def mp_next_track(self):
        p = getattr(self.notifier, "player", None)
        if not p:
            return
        p.next_track()
        mp = self.root.ids.get("mini_player")
        if mp:
            mp.duration = 0.0
            mp._has_duration = False
            mp.position = 0.0
        self.update_mini_player_state(True)

    def mp_close(self):
        p = getattr(self.notifier, "player", None)
        if p:
            p.stop()
        self.hide_mini_player()

    def _on_mp_seek(self, value):
        self._seek_to(value)

    def _on_mp_volume(self, value):
        p = getattr(self.notifier, "player", None)
        if not p:
            return
        try:
            p.set_volume(value)
        except Exception:
            if p.sound:
                try:
                    p.sound.volume = float(value)
                except Exception:
                    pass

    def toggle_mini_player(self):
        p = getattr(self.notifier, "player", None)
        if not p:
            return
        snd = p.sound
        if snd and not p.paused and getattr(snd, "state", "") == "play":
            p.pause()
            self.update_mini_player_state(False)
        else:
            p.resume() if p.paused else p.play()
            self.update_mini_player_state(True)

    # ------------------------------ Tiện ích thời gian & kiểm tra xung đột ------------------------------
    def _hhmm_to_min(self, s: str) -> int | None:
        try:
            h, m = (s or "").split(":")
            h, m = int(h), int(m)
            if 0 <= h < 24 and 0 <= m < 60:
                return h * 60 + m
        except Exception:
            pass
        return None

    def _overlap(self, a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """Hai khoảng [start, end) có đè nhau không (cho phép chạm biên)."""
        return max(a_start, b_start) < min(a_end, b_end)

    def _has_conflict_on_day(self, day_key: str, start_min: int, end_min: int, exclude_id: str | None = None):
        """
        Kiểm tra trùng lịch trong ngày: trả về (True, rec_conflict) nếu có.
        exclude_id: bỏ qua chính nó lúc sửa.
        """
        items = get_schedule_by_day(day_key) or []
        for it in items:
            if exclude_id and it.get("id") == exclude_id:
                continue
            s2 = self._hhmm_to_min(it.get("time", ""))
            e2 = self._hhmm_to_min(it.get("end", ""))
            if s2 is None or e2 is None:
                continue
            if self._overlap(start_min, end_min, s2, e2):
                return True, it
        return False, None

    def refresh_notes(self, query: str = None):
        if not getattr(self, "note_manager", None):
            # print("[refresh_notes] note_manager is None")
            return

        notes_view = None
        try:
            notes_view = self.root.ids.get('notes_view')
        except Exception:
            pass

        if query is not None:
            notes = self.note_manager.search_notes(query or "")
            # print(f"[refresh_notes] search_notes({query!r}) -> {len(notes)} items")
        else:
            notes = self.note_manager.list_notes()
            # print(f"[refresh_notes] list_notes() -> {len(notes)} items")

        from datetime import datetime

        data = []
        for n in notes:
            rem_txt = ""
            when_str = getattr(n, "reminder_at", None)

            # print(f"[refresh_notes] note {n.id} title={n.title!r} reminder_at={when_str!r}")

            if when_str:
                try:
                    safe_str = when_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(safe_str)
                    rem_txt = self._format_note_reminder_dt(dt)
                except Exception as e:
                    print("[refresh_notes] parse reminder err:", e)
                    # fallback: show raw
                    rem_txt = when_str

            item = {
                "note_id": n.id,
                "title": n.title,
                "content": n.content,
                "reminder_text": rem_txt,
            }
            print("   -> rv item:", item)
            data.append(item)

        print("[refresh_notes] final rv.data:", data)

        if notes_view is not None:
            notes_view.data = data

        # --- hiển thị / ẩn label rỗng ---
        try:
            empty = self.screen.ids.get("notes_empty_label")
        except Exception:
            empty = None

        if empty:
            has_items = len(data) > 0
            empty.opacity = 0 if has_items else 1
            empty.height = 0 if has_items else dp(32)

    def delete_note(self, note_id):
        if not getattr(self, "note_manager", None):
            return
        self.note_manager.delete_note(note_id)
        self.refresh_notes()

    # ------------------------------ Notes Dialogs & handlers ------------------------------
    def open_create_note_dialog(self):
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer, MDDialogButtonContainer
        from kivy.uix.widget import Widget

        TEAL = (0.39, 0.74, 0.67, 1)
        TEAL_PRESSED = (0.33, 0.63, 0.57, 1)

        wrapper = MDBoxLayout(
            orientation="vertical",
            spacing=dp(16),
            padding=[dp(20), dp(20), dp(20), dp(12)],
            size_hint_y=None,
        )

        # ----- Tiêu đề căn giữa -----
        title_lbl = MDLabel(
            text="Tạo ghi chú văn bản",
            bold=True,
            font_size="20sp",
            halign="center",
            theme_text_color="Custom",
            text_color=self.on_surface,
            size_hint_y=None,
            height=dp(28),
        )
        wrapper.add_widget(title_lbl)

        # ----- TextField: filled, không viền -----
        title_tf = MDTextField(
            hint_text="Tiêu đề",
            mode="filled",          # <--- CHỈNH Ở ĐÂY
            multiline=False,
            size_hint_y=None,
            height=dp(42),
        )
        title_tf.radius = [dp(14)]
        title_tf.fill_color_normal = (1, 1, 1, 1)
        title_tf.fill_color_focus = (1, 1, 1, 1)
        title_tf.line_color_normal = (0, 0, 0, 0)
        title_tf.line_color_focus = (0, 0, 0, 0)

        content_tf = MDTextField(
            hint_text="Ghi chú",
            mode="filled",          # <--- VÀ Ở ĐÂY
            multiline=True,
            max_height=dp(160),
            size_hint_y=None,
            height=dp(120),
        )
        content_tf.radius = [dp(14)]
        content_tf.fill_color_normal = (1, 1, 1, 1)
        content_tf.fill_color_focus = (1, 1, 1, 1)
        content_tf.line_color_normal = (0, 0, 0, 0)
        content_tf.line_color_focus = (0, 0, 0, 0)

        wrapper.add_widget(title_tf)
        wrapper.add_widget(content_tf)

        # --- Nhắc giờ ---
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon

        self._note_create_reminder_dt = None

        rem_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=[0, dp(4), 0, 0],
            spacing=dp(6),
        )

        rem_btn = MDButton(
            MDButtonIcon(icon="bell-outline"),
            MDButtonText(text="Đặt nhắc hẹn (tùy chọn)"),
            style="text",
            on_release=lambda *_: self._pick_note_reminder("create"),
            size_hint_x=None,
            width=dp(180),
        )

        rem_lbl = MDLabel(
            theme_text_color="Secondary",
            size_hint_x=1,
            halign="right",
            valign="middle",
        )
        rem_lbl.bind(texture_size=lambda *_: setattr(rem_lbl, "height", dp(20)))

        rem_row.add_widget(rem_btn)
        rem_row.add_widget(rem_lbl)
        wrapper.add_widget(rem_row)

        # lưu reference để cập nhật text khi chọn xong
        self._note_create_reminder_lbl = rem_lbl

        wrapper.bind(minimum_height=wrapper.setter("height"))

        content = MDDialogContentContainer(wrapper)

        btn_cancel = MDButton(
            MDButtonText(text="HUỶ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self._close_note_dialog()),
        )

        btn_create = MDButton(
            MDButtonText(text="TẠO", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (
                setattr(x, "md_bg_color", TEAL),
                self._do_create_note(title_tf.text, content_tf.text),
            ),
        )

        buttons = MDDialogButtonContainer(
            Widget(),
            btn_cancel,
            btn_create,
            spacing="12dp",
            padding=[dp(16), 0, dp(16), dp(16)],
        )

        self._note_dialog_inputs = {"title": title_tf, "content": content_tf}
        self.note_dialog = MDDialog(content, buttons)
        self.note_dialog.radius = [dp(18)]
        self.note_dialog.size_hint = (0.96, None)

        def _autofit(*_):
            self.note_dialog.height = min(dp(420), wrapper.height + dp(140))

        Clock.schedule_once(_autofit, 0)
        self.note_dialog.open()

    def open_edit_note_dialog(self, note_id: str):
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.label import MDLabel
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer, MDDialogButtonContainer
        from kivy.uix.widget import Widget

        TEAL = (0.39, 0.74, 0.67, 1)
        TEAL_PRESSED = (0.33, 0.63, 0.57, 1)
        RED = (0.91, 0.33, 0.31, 1)
        RED_PRESSED = (0.78, 0.28, 0.26, 1)

        # load note hiện tại
        note = None
        try:
            if getattr(self, "note_manager", None):
                self.note_manager.load()
                notes = self.note_manager.list_notes()
                note = next((n for n in notes if n.id == note_id), None)
        except Exception as e:
            print("Load note err:", e)

        title_val = note.title if note else ""
        content_val = note.content if note else ""

        # đọc reminder cũ từ note.reminder_at (nếu có)
        from datetime import datetime
        self._note_edit_reminder_dt = None
        rem_initial_text = "--/--"
        try:
            if note and getattr(note, "reminder_at", None):
                dt = datetime.fromisoformat(note.reminder_at)
                self._note_edit_reminder_dt = dt
                rem_initial_text = self._format_note_reminder_dt(dt)
        except Exception as e:
            print("parse existing note reminder err:", e)
            rem_initial_text = "--/--"

        wrapper = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(16), dp(16), dp(16), dp(8)],
            size_hint_y=None,
        )

        title_lbl = MDLabel(
            text="Chỉnh sửa ghi chú",
            bold=True,
            font_size="18sp",
            size_hint_y=None,
            height=dp(24),
        )
        wrapper.add_widget(title_lbl)

        title_tf = MDTextField(
            text=title_val,
            hint_text="Tiêu đề",
            multiline=False,
            mode="outlined",
            size_hint_y=None,
            height=dp(44),
        )
        content_tf = MDTextField(
            text=content_val,
            hint_text="Nội dung",
            multiline=True,
            mode="outlined",
            size_hint_y=None,
            height=dp(120),
        )

        wrapper.add_widget(title_tf)
        wrapper.add_widget(content_tf)

        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon

        # tạm thời: chưa có reminder cũ → None
        # self._note_edit_reminder_dt = None

        rem_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=[0, dp(4), 0, 0],
            spacing=dp(6),
        )

        rem_btn = MDButton(
            MDButtonIcon(icon="bell-outline"),
            MDButtonText(text="Thời gian nhắc"),
            style="text",
            on_release=lambda *_: self._pick_note_reminder("edit"),
            size_hint_x=None,
            width=dp(180),
        )

        rem_lbl = MDLabel(
            text=rem_initial_text,
            theme_text_color="Secondary",
            size_hint_x=1,
            halign="right",
            valign="middle",
        )
        rem_lbl.bind(texture_size=lambda *_: setattr(rem_lbl, "height", dp(20)))

        rem_row.add_widget(rem_btn)
        rem_row.add_widget(rem_lbl)
        wrapper.add_widget(rem_row)

        self._note_edit_reminder_lbl = rem_lbl

        wrapper.bind(minimum_height=wrapper.setter("height"))

        content = MDDialogContentContainer(wrapper)

        btn_cancel = MDButton(
            MDButtonText(
                text="HUỶ",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (setattr(x, "md_bg_color", TEAL), self._close_note_dialog()),
        )

        btn_delete = MDButton(
            MDButtonText(
                text="XOÁ",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=RED,
            on_press=lambda x: setattr(x, "md_bg_color", RED_PRESSED),
            on_release=lambda x: (
                setattr(x, "md_bg_color", RED),
                self._confirm_delete_note(note_id),   # 👈 gọi hàm mới
            ),
        )

        btn_update = MDButton(
            MDButtonText(
                text="CẬP NHẬT",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            on_press=lambda x: setattr(x, "md_bg_color", TEAL_PRESSED),
            on_release=lambda x: (
                setattr(x, "md_bg_color", TEAL),
                self._do_update_note(note_id, title_tf.text, content_tf.text),
            ),
        )

        buttons = MDDialogButtonContainer(
            btn_delete,
            Widget(),
            btn_cancel,
            btn_update,
            spacing="10dp",
            padding=[dp(16), 0, dp(16), dp(16)],
        )

        self._note_dialog_inputs = {"title": title_tf, "content": content_tf}
        self.note_dialog = MDDialog(content, buttons)
        self.note_dialog.radius = [dp(18)]
        self.note_dialog.size_hint = (0.96, None)

        def _autofit(*_):
            self.note_dialog.height = min(dp(440), wrapper.height + dp(130))

        Clock.schedule_once(_autofit, 0)
        self.note_dialog.open()

    def _close_note_dialog(self):
        try:
            if getattr(self, "note_dialog", None):
                self.note_dialog.dismiss()
        except Exception:
            pass
        finally:
            self.note_dialog = None
            self._note_dialog_inputs = None

    def _do_create_note(self, title: str, content: str):
        """Tạo ghi chú mới.

        - Nếu cả tiêu đề *và* nội dung đều trống -> không tạo.
        """
        title = (title or "").strip()
        content = (content or "").strip()

        # Nếu người dùng không gõ gì cả -> huỷ
        if not title and not content:
            self.show_message("Đã huỷ ghi chú trống.")
            self._close_note_dialog()
            return

        # datetime đã được chọn trong _open_note_time_picker (mode=create)
        when_dt = getattr(self, "_note_create_reminder_dt", None)
        iso = when_dt.isoformat() if when_dt else None
        print("[_do_create_note] title=", title, "content=", content, "reminder_iso=", iso)

        try:
            if not getattr(self, "note_manager", None):
                print("NoteManager not initialized")
            else:
                note = self.note_manager.add_note(title or "", content or "", reminder_at=iso)
                print("[_do_create_note] created note:", note)
                Clock.schedule_once(lambda *_: self.refresh_notes(), 0.1)

                # schedule notify trong runtime hiện tại
                if note and when_dt:
                    self._schedule_note_notification(
                        note.id, when_dt, note.title, note.content
                    )
        except Exception as e:
            print("Create note err:", e)
        finally:
            self._close_note_dialog()
            self._note_create_reminder_dt = None

    def _do_update_note(self, note_id: str, title: str, content: str):
        try:
            when_dt = getattr(self, "_note_edit_reminder_dt", None)
            iso = when_dt.isoformat() if when_dt else None

            if getattr(self, "note_manager", None):
                self.note_manager.update_note(
                    note_id,
                    title=title,
                    content=content,
                    reminder_at=iso,
                )
                Clock.schedule_once(lambda *_: self.refresh_notes(), 0.1)

                # đặt lại reminder (nếu có)
                try:
                    if when_dt:
                        # lấy lại note mới để có title/content cập nhật
                        notes = self.note_manager.list_notes()
                        note = next((n for n in notes if n.id == note_id), None)
                        if note:
                            self._schedule_note_notification(
                                note.id, when_dt, note.title, note.content
                            )
                except Exception as e:
                    print("reschedule note reminder err:", e)

        except Exception as e:
            print("Update note err:", e)
        finally:
            self._close_note_dialog()
            self._note_edit_reminder_dt = None

    def _do_delete_note(self, note_id: str):
        try:
            if getattr(self, "note_manager", None):
                self.note_manager.delete_note(note_id)

            # xoá cache reminder nếu có
            if hasattr(self, "_note_reminders") and self._note_reminders:
                self._note_reminders.pop(note_id, None)

            Clock.schedule_once(lambda *_: self.refresh_notes(), 0.1)
        except Exception as e:
            print("Delete note err:", e)
        finally:
            self._close_note_dialog()

    def _confirm_delete_note(self, note_id: str):
        """Hiện dialog xác nhận xoá ghi chú, giống TKB."""
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer, MDDialogButtonContainer
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.label import MDLabel
        from kivy.uix.widget import Widget

        TEAL = (0.39, 0.74, 0.67, 1)
        RED  = (0.91, 0.33, 0.31, 1)

        dialog_width = min(dp(460), Window.width * 0.95)

        msg = MDLabel(
            text="Bạn có chắc muốn xoá ghi chú này không?",
            halign="center",
            theme_text_color="Custom",
            text_color=(0, 0, 0, 1),
            font_size="16sp",
            size_hint=(1, None),
            max_lines=2,
            shorten=True,
            shorten_from="right",
        )
        msg.text_size = (dialog_width - dp(48), None)
        msg.texture_update()
        msg.height = msg.texture_size[1]

        box = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=msg.height + dp(8),
            padding=[dp(12), dp(12), dp(12), dp(2)],
        )
        box.add_widget(msg)

        content = MDDialogContentContainer(
            box,
            padding=[0, 0, 0, 0],
            spacing=dp(0),
        )

        def _do_ok(*_):
            # dùng lại logic cũ trong _do_delete_note
            self._do_delete_note(note_id)
            dialog.dismiss()

        btn_cancel = MDButton(
            MDButtonText(text="HUỶ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="filled",
            theme_bg_color="Custom",
            md_bg_color=TEAL,
            radius=[dp(14)],
            size_hint=(None, None),
            height=dp(34),
            on_release=lambda *_: dialog.dismiss(),
        )

        btn_ok = MDButton(
            MDButtonText(text="XOÁ", theme_text_color="Custom", text_color=(1, 1, 1, 1)),
            style="filled",
            theme_bg_color="Custom",
            md_bg_color=RED,
            radius=[dp(14)],
            size_hint=(None, None),
            height=dp(34),
            on_release=_do_ok,
        )

        dialog = MDDialog(
            content,
            MDDialogButtonContainer(
                Widget(),
                btn_cancel,
                btn_ok,
                Widget(),
                spacing="10dp",
                padding=[dp(8), dp(4), dp(8), dp(8)],
            ),
        )
        dialog.size_hint = (None, None)
        dialog.width = dialog_width
        dialog.height = dp(130)
        dialog.theme_bg_color = "Custom"
        dialog.md_bg_color = (1, 1, 1, 1)
        dialog.radius = [dp(16)]
        dialog.open()

    def _open_note_time_picker(self, mode: str, date_obj, parent_dialog):
        """
        Mở time picker sau khi đã chọn NGÀY cho ghi chú.
        mode: 'create' hoặc 'edit'
        """
        from datetime import datetime
        picker = MDTimePickerDialVertical()

        def _reopen_parent():
            # đóng time picker + mở lại dialog ghi chú
            try:
                picker.dismiss()
            except Exception:
                pass
            if parent_dialog:
                Clock.schedule_once(lambda *_: parent_dialog.open(), 0.1)

        def _on_ok(inst):
            t = getattr(inst, "time", None)
            if not t:
                # Không chọn giờ -> chỉ đóng time picker & mở lại dialog ghi chú
                _reopen_parent()
                return

            dt_val = datetime(
                year=date_obj.year,
                month=date_obj.month,
                day=date_obj.day,
                hour=t.hour,
                minute=t.minute,
            )

            # 🔒 KHÔNG CHO CHỌN THỜI GIAN NHẮC TRONG QUÁ KHỨ
            try:
                now = datetime.now()
                if dt_val <= now:
                    self.show_message("Thời gian nhắc phải lớn hơn thời gian hiện tại.")
                    # Giữ nguyên time picker để user chỉnh lại, KHÔNG đóng
                    return
            except Exception as e:
                print("validate note reminder time err:", e)

            # Lưu lại datetime + update label hiển thị
            if mode == "create":
                self._note_create_reminder_dt = dt_val
                lbl = getattr(self, "_note_create_reminder_lbl", None)
            else:
                self._note_edit_reminder_dt = dt_val
                lbl = getattr(self, "_note_edit_reminder_lbl", None)

            if lbl:
                lbl.text = self._format_note_reminder_dt(dt_val)

            _reopen_parent()

        def _on_cancel(inst):
            # Huỷ chọn giờ -> đóng time picker + mở lại dialog ghi chú
            _reopen_parent()

        picker.bind(on_ok=_on_ok, on_cancel=_on_cancel)
        picker.open()

    # ============================== NOTE REMINDERS ==============================
    def _format_note_reminder_dt(self, dt_obj):
        """Hiển thị ngày giờ kiểu '24 tháng 11, 8:00'."""
        if not dt_obj:
            return "Không nhắc"

        try:
            d = dt_obj
            return f"{d.day} tháng {d.month}, {d.hour:02d}:{d.minute:02d}"
        except Exception:
            return "Không nhắc"

    def _pick_note_reminder(self, mode: str):
        """
        Chọn NGÀY + GIỜ cho ghi chú bằng dialog calendar custom.
        mode: "create" hoặc "edit"
        """
        from datetime import datetime, date
        import calendar
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.label import MDLabel
        from kivy.uix.gridlayout import GridLayout
        from kivy.uix.widget import Widget
        from kivy.metrics import dp

        # dialog ghi chú hiện tại (create hoặc edit)
        parent_dialog = getattr(self, "note_dialog", None)
        if parent_dialog and getattr(parent_dialog, "attached_to_window", False):
            try:
                parent_dialog.dismiss()
            except Exception:
                pass

        today = datetime.now().date()
        current = [today.year, today.month]  # mutable [year, month]

        # ====== layout gốc của calendar ======
        root_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(15), dp(50), dp(15), dp(10)],
            size_hint_y=None,
        )
        root_box.bind(minimum_height=root_box.setter("height"))

        # ----- Header: nút prev / tháng / next -----
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
        )

        btn_prev = MDButton(
            MDButtonText(text="<"),
            style="text",
            theme_bg_color="Custom",
            md_bg_color=(0, 0, 0, 0),
            size_hint_x=None,
            width=dp(48),
        )

        month_lbl = MDLabel(
            text="",
            bold=True,
            halign="center",
            font_size="18sp",
            size_hint_x=1,
        )

        btn_next = MDButton(
            MDButtonText(text=">"),
            style="text",
            theme_bg_color="Custom",
            md_bg_color=(0, 0, 0, 0),
            size_hint_x=None,
            width=dp(48),
        )

        header.add_widget(btn_prev)
        header.add_widget(month_lbl)
        header.add_widget(btn_next)
        root_box.add_widget(header)

        # ----- Hàng thứ trong tuần -----
        weekday_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(24),
            padding=[0, 0, 0, 0],
        )

        # Thứ bắt đầu từ T2 -> CN
        weekday_labels = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        for txt in weekday_labels:
            weekday_row.add_widget(
                MDLabel(
                    text=txt,
                    halign="center",
                    font_size="13sp",
                    theme_text_color="Secondary",
                    size_hint_x=1,
                )
            )
        root_box.add_widget(weekday_row)

        # ----- Grid ngày -----
        days_grid = GridLayout(
            cols=7,
            spacing=(dp(6), dp(6)),
            padding=[0, 0, 0, 0],

            size_hint=(None, None),

            row_force_default=True,
            row_default_height=dp(32),

            col_force_default=True,          # <--- cái quan trọng nhất!
            col_default_width=dp(34),        # <--- width cố định cho mỗi cột
        )
        days_grid.bind(
            minimum_height=days_grid.setter("height"),
            minimum_width=days_grid.setter("width"),   # <--- tự co theo nội dung
        )

        # bọc grid vào box để canh giữa
        grid_wrapper = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            padding=[0, 0, 0, 0],
        )
        grid_wrapper.bind(minimum_height=grid_wrapper.setter("height"))
        grid_wrapper.add_widget(Widget(size_hint_x=1))
        grid_wrapper.add_widget(days_grid)
        grid_wrapper.add_widget(Widget(size_hint_x=1))

        root_box.add_widget(grid_wrapper)

        # ----- Footer: chỉ có nút HUỶ, tách hẳn khỏi grid -----
        footer = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=[0, dp(4), 0, 0],
            spacing=dp(10),
        )

        footer.add_widget(Widget(size_hint_x=1))

        btn_cancel = MDButton(
            MDButtonText(text="HUỶ"),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=self.primary_teal if hasattr(self, "primary_teal") else (0.39, 0.74, 0.67, 1),
            size_hint=(None, None),
            height=dp(36),
            width=dp(80),
        )
        footer.add_widget(btn_cancel)
        root_box.add_widget(footer)

        # ====== logic render calendar ======
        calendar.setfirstweekday(calendar.MONDAY)

        def _update_month_label():
            y, m = current
            month_lbl.text = f"Tháng {m} {y}"

        def _on_day_selected(day: int, *_):
            y, m = current
            try:
                selected = date(y, m, day)
            except Exception:
                return

            # đóng dialog lịch, mở time picker cho ngày đã chọn
            dialog.dismiss()
            self._open_note_time_picker(mode, selected, parent_dialog)

        def _rebuild_days(*_):
            days_grid.clear_widgets()
            y, m = current
            _update_month_label()

            first_weekday, num_days = calendar.monthrange(y, m)
            # first_weekday: 0=Mon, 6=Sun (đã set firstweekday=MONDAY)

            # Ô trống trước ngày 1
            for _ in range(first_weekday):
                days_grid.add_widget(Widget())

            # Các ngày trong tháng
            for d in range(1, num_days + 1):
                btn = MDButton(
                    MDButtonText(text=str(d)),
                    style="text",
                    theme_bg_color="Custom",
                    md_bg_color=(0, 0, 0, 0),
                    size_hint=(None, None),  # <--- không chiếm full cột
                    width=dp(32),
                    height=dp(32),
                    on_release=lambda _, _day=d: _on_day_selected(_day),
                )
                days_grid.add_widget(btn)

        def _go_prev_month(*_):
            y, m = current
            m -= 1
            if m == 0:
                m = 12
                y -= 1
            current[0], current[1] = y, m
            _rebuild_days()

        def _go_next_month(*_):
            y, m = current
            m += 1
            if m == 13:
                m = 1
                y += 1
            current[0], current[1] = y, m
            _rebuild_days()

        btn_prev.bind(on_release=_go_prev_month)
        btn_next.bind(on_release=_go_next_month)

        def _on_cancel(*_):
            dialog.dismiss()
            # mở lại dialog ghi chú, không đổi reminder
            if parent_dialog:
                Clock.schedule_once(lambda *_: parent_dialog.open(), 0.1)

        btn_cancel.bind(on_release=_on_cancel)

        # render lần đầu
        _rebuild_days()

        # ====== Tạo & mở dialog ======
        content = MDDialogContentContainer(root_box)
        dialog = MDDialog(content)
        dialog.radius = [dp(24)]
        dialog.size_hint = (0.9, None)

        def _autofit(*_):
            dialog.height = min(dp(420), root_box.height + dp(40))
            dialog.pos_hint = {"center_x": 0.5, "center_y": 0.5}
            
        Clock.schedule_once(_autofit, 0)
        dialog.open()

    def _schedule_note_notification(self, note_id: str, when_dt, title: str, content: str):
        """Bắn notify_system vào đúng thời điểm (simple version – chỉ chạy khi app còn sống)."""
        from datetime import datetime

        if not when_dt:
            return

        # đảm bảo dict tồn tại
        if not hasattr(self, "_note_reminders") or self._note_reminders is None:
            self._note_reminders = {}

        try:
            self._note_reminders[note_id] = when_dt.isoformat()
        except Exception as e:
            print("store note reminder err:", e)

        try:
            delay = (when_dt - datetime.now()).total_seconds()
        except Exception:
            delay = 0

        if delay < 0:
            delay = 0.1

        print("[NOTE REMINDER] schedule", note_id, "at", when_dt, "delay=", delay)

        def _fire(*_):
            try:
                msg_title = title or "Nhắc ghi chú"
                msg_body = content or "Tới giờ xem ghi chú."
                print("[NOTE REMINDER] FIRE", note_id, "->", msg_title)
                notify_system(msg_title, msg_body)
            except Exception as e:
                print("notify_system note err:", e)

        Clock.schedule_once(_fire, delay)

    def _reschedule_note_reminders_on_start(self):
        if not getattr(self, "note_manager", None):
            return

        from datetime import datetime

        try:
            self.note_manager.load()
            notes = self.note_manager.list_notes()
        except Exception as e:
            print("load notes for reschedule err:", e)
            return

        now = datetime.now()
        for n in notes:
            when_str = getattr(n, "reminder_at", None)
            if not when_str:
                continue
            try:
                dt = datetime.fromisoformat(when_str)
            except Exception:
                continue

            if dt <= now:
                continue

            try:
                self._schedule_note_notification(n.id, dt, n.title, n.content)
            except Exception as e:
                print("schedule note on_start err:", e)

    # ============================== NOTES: FAB MENU (giống Keep) ==============================
    def _handle_notes_menu_option(self, callback):
        """Đóng dialog menu rồi gọi callback tương ứng."""
        try:
            if getattr(self, "_notes_menu_dialog", None):
                self._notes_menu_dialog.dismiss()
        except Exception:
            pass
        finally:
            self._notes_menu_dialog = None

        try:
            if callback:
                callback()
        except Exception as e:
            print("Notes menu option err:", e)

    def open_notes_fab_menu(self):
        """
        Mở menu chọn loại ghi chú:
        - Văn bản
        - Danh sách
        - Bản vẽ
        - Hình ảnh
        - Âm thanh
        """
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText, MDButtonIcon
        from kivymd.uix.label import MDLabel
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer
        from kivy.uix.widget import Widget

        # nếu đã mở thì không mở thêm
        if getattr(self, "_notes_menu_dialog", None):
            try:
                self._notes_menu_dialog.dismiss()
            except Exception:
                pass
            self._notes_menu_dialog = None

        wrapper = MDBoxLayout(
            orientation="vertical",
            spacing=dp(4),
            padding=[dp(16), dp(16), dp(16), dp(8)],
            size_hint_y=None,
        )

        title_lbl = MDLabel(
            text="Tạo ghi chú",
            bold=True,
            font_size="18sp",
            size_hint_y=None,
            height=dp(24),
        )
        wrapper.add_widget(title_lbl)

        def add_option(icon_name: str, text: str, cb):
            btn = MDButton(
                MDButtonIcon(
                    icon=icon_name,
                    theme_text_color="Custom",
                    text_color=self.on_surface if hasattr(self, "on_surface") else (0, 0, 0, 1),
                ),
                MDButtonText(
                    text=text,
                    theme_text_color="Custom",
                    text_color=self.on_surface if hasattr(self, "on_surface") else (0, 0, 0, 1),
                ),
                style="text",
                theme_bg_color="Custom",
                md_bg_color=(0, 0, 0, 0),
                size_hint_y=None,
                height=dp(40),
                on_release=lambda *_: self._handle_notes_menu_option(cb),
            )
            wrapper.add_widget(btn)

        # 5 loại ghi chú giống Keep
        add_option("text-box", "Ghi chú văn bản", self.open_create_note_dialog)
        add_option("format-list-bulleted", "Ghi chú danh sách", self.open_create_list_note)
        add_option("gesture", "Ghi chú bản vẽ", self.open_create_drawing_note)
        add_option("image", "Ghi chú hình ảnh", self.open_create_image_note)
        add_option("microphone", "Ghi chú âm thanh", self.open_create_audio_note)

        # thêm chút khoảng trống dưới
        wrapper.add_widget(Widget(size_hint_y=None, height=dp(4)))
        wrapper.bind(minimum_height=wrapper.setter("height"))

        content = MDDialogContentContainer(wrapper)

        dialog = MDDialog(content)
        dialog.radius = [dp(18)]
        dialog.size_hint = (0.96, None)

        def _autofit(*_):
            dialog.height = min(dp(420), wrapper.height + dp(40))

        Clock.schedule_once(_autofit, 0)

        self._notes_menu_dialog = dialog
        dialog.open()

    # ----- Stub cho các loại ghi chú khác (tạm thời) -----
    def open_create_list_note(self):
        # TODO: triển khai dialog tạo ghi chú dạng checklist
        self.show_message("Ghi chú danh sách: tính năng sẽ được thêm sau.")

    def open_create_drawing_note(self):
        # TODO: mở màn vẽ (Canvas) rồi lưu thành note
        self.show_message("Ghi chú bản vẽ: tính năng sẽ được thêm sau.")

    def open_create_image_note(self):
        # TODO: chọn ảnh từ thư viện / camera rồi lưu
        self.show_message("Ghi chú hình ảnh: tính năng sẽ được thêm sau.")

    def open_create_audio_note(self):
        # TODO: mở ghi âm, lưu file âm thanh gắn với note
        self.show_message("Ghi chú âm thanh: tính năng sẽ được thêm sau.")

    def _toggle_note_fab_menu(self):
        try:
            ids = self.root.ids
        except Exception:
            return

        menu = ids.get("fab_menu")
        if not menu:
            return

        is_open = not menu.disabled  # đang mở?
        menu.disabled = is_open
        menu.opacity = 0 if is_open else 1

    def on_note_type_pressed(self, note_type: str):
        """Callback khi chọn 1 loại ghi chú từ fab_menu."""
        # đóng menu
        self._toggle_note_fab_menu()

        if note_type == "text":
            # mở dialog Tiêu đề + Ghi chú (đã có)
            try:
                self.open_create_note_dialog()
            except Exception as e:
                print("open_create_note_dialog err:", e)
        elif note_type == "checklist":
            self.show_message("Ghi chú dạng DANH SÁCH chưa làm, sẽ cập nhật sau.")
        elif note_type == "drawing":
            self.show_message("Ghi chú dạng BẢN VẼ chưa làm, sẽ cập nhật sau.")
        elif note_type == "image":
            self.show_message("Ghi chú dạng HÌNH ẢNH chưa làm, sẽ cập nhật sau.")
        elif note_type == "audio":
            self.show_message("Ghi chú dạng ÂM THANH chưa làm, sẽ cập nhật sau.")

    def _update_search_ui(self):
        """Cập nhật hint & trạng thái thanh search (search global, tạm dùng cho notes)."""
        try:
            search = self.screen.ids.get("global_search")
        except Exception:
            search = None

        if not search:
            return

        # Thanh search luôn là search chung
        search.hint_text = "Tìm kiếm..."
        search.disabled = False
        search.readonly = False
        # Giữ nguyên text người dùng gõ
        # search.text = ""

    def on_search_text(self, query: str):
        """Callback từ thanh search global.

        - Bất kể đang ở màn nào, khi có query -> hiển thị màn search_results.
        - Hiện tại: search chỉ trên ghi chú.
        """
        query = (query or "").strip()

        # Nếu thanh search trống:
        if not query:
            # nếu đang ở màn search_results -> quay lại màn trước đó (nếu có)
            if getattr(self, "current_section", None) == "search_results":
                prev = getattr(self, "_section_before_search", None)
                if prev and prev in ("timetable", "notes"):
                    self._switch_section(prev)
                else:
                    self._switch_section("timetable")

            # clear kết quả & ẩn label
            self._clear_search_results()
            return

        # Lần đầu bắt đầu search từ màn khác -> lưu màn trước
        if getattr(self, "current_section", None) != "search_results":
            self._section_before_search = self.current_section

        # Lấy note theo query
        if getattr(self, "note_manager", None):
            notes = self.note_manager.search_notes(query)
        else:
            notes = []

        # Chuyển sang màn search_results và hiển thị
        self._switch_section("search_results")
        self._fill_search_results(notes)

    def on_search_submit(self, query: str):
        """Khi nhấn Enter trên thanh search."""
        self.on_search_text(query)

    def _switch_section(self, name: str):
        """Chuyển section + đổi screen trong sm nếu có."""
        self.current_section = name
        try:
            sm = self.screen.ids.get("sm")
        except Exception:
            sm = None

        try:
            if sm and name in getattr(sm, "screen_names", []):
                sm.current = name
        except Exception:
            pass
        self._update_fab_visibility()

    def _clear_search_results(self):
        """Xoá dữ liệu search_results và ẩn label 'Không có kết quả'."""
        try:
            rv = self.screen.ids.get("search_results_view")
            empty_lbl = self.screen.ids.get("search_empty_label")
        except Exception:
            return

        if rv:
            rv.data = []

        if empty_lbl:
            empty_lbl.opacity = 0
            empty_lbl.height = 0

    def _fill_search_results(self, notes):
        try:
            rv = self.screen.ids.get("search_results_view")
            empty_lbl = self.screen.ids.get("search_empty_label")
        except Exception:
            rv = None
            empty_lbl = None

        if not rv:
            return

        from datetime import datetime

        data = []
        for n in notes:
            rem_txt = ""
            when_str = getattr(n, "reminder_at", None)
            if when_str:
                try:
                    dt = datetime.fromisoformat(when_str)
                    rem_txt = self._format_note_reminder_dt(dt)
                except Exception as e:
                    print("parse reminder err:", e)

            data.append({
                "note_id": n.id,
                "title": n.title,
                "content": n.content,
                "reminder_text": rem_txt,
            })

        rv.data = data

        if empty_lbl:
            if data:
                empty_lbl.opacity = 0
                empty_lbl.height = 0
            else:
                empty_lbl.opacity = 1
                empty_lbl.height = dp(24)

    def _update_fab_visibility(self):
        """Ẩn/hiện FAB khi vào màn search_results."""
        try:
            fab = self.root.ids.get("corner_fab")
        except Exception:
            return
        if not fab:
            return
        
        if self.current_section == "search_results":
            fab.opacity = 0
            fab.disabled = True
        else:
            fab.opacity = 1
            fab.disabled = False

    def _pick_date_custom(self, callback):
        """
        Mở dialog chọn ngày: Hôm nay / Ngày mai / Chọn ngày khác.
        callback(date_obj)
        """
        from datetime import datetime, timedelta
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)

        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.label import MDLabel
        from kivy.metrics import dp
        from kivy.uix.textinput import TextInput

        # layout
        box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            padding=[dp(16), dp(16), dp(16), dp(16)],
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))

        lbl = MDLabel(
            text="Chọn ngày",
            bold=True,
            font_size="18sp",
            size_hint_y=None,
            height=dp(24)
        )
        box.add_widget(lbl)

        # hôm nay
        btn_today = MDButton(
            MDButtonText(text=f"Hôm nay ({today.strftime('%d/%m')})"),
            style="text",
            on_release=lambda *_: (callback(today), dialog.dismiss()),
        )
        box.add_widget(btn_today)

        # ngày mai
        btn_tmr = MDButton(
            MDButtonText(text=f"Ngày mai ({tomorrow.strftime('%d/%m')})"),
            style="text",
            on_release=lambda *_: (callback(tomorrow), dialog.dismiss()),
        )
        box.add_widget(btn_tmr)

        # chọn ngày khác
        other_label = MDLabel(
            text="Ngày khác (dd/mm/yyyy):",
            size_hint_y=None,
            height=dp(20),
        )
        box.add_widget(other_label)

        other_tf = TextInput(
            hint_text="ví dụ: 25/01/2025",
            size_hint_y=None,
            height=dp(40),
            multiline=False,
        )
        box.add_widget(other_tf)

        def _confirm_other(*_):
            txt = other_tf.text.strip()
            try:
                d, m, y = txt.split("/")
                import datetime
                day = datetime.date(int(y), int(m), int(d))
                callback(day)
                dialog.dismiss()
            except:
                self.show_message("Ngày không hợp lệ. Định dạng dd/mm/yyyy.")

        btn_ok = MDButton(
            MDButtonText(text="OK"),
            style="elevated",
            on_release=_confirm_other,
        )

        box.add_widget(btn_ok)

        content = MDDialogContentContainer(box)
        dialog = MDDialog(content)
        dialog.size_hint = (0.9, None)

        def _autofit(*_):
            dialog.height = min(dp(400), box.height + dp(60))
        Clock.schedule_once(_autofit, 0)

        dialog.open()

    def _pick_date_quick(self, callback):
        """
        Mở dialog chọn ngày (không gõ tay):
        - Hôm nay
        - Ngày mai
        - Tuần sau
        callback(date_obj: datetime.date)
        """
        from datetime import datetime, timedelta
        from kivymd.uix.dialog import MDDialog, MDDialogContentContainer
        from kivymd.uix.boxlayout import MDBoxLayout
        from kivymd.uix.button import MDButton, MDButtonText
        from kivymd.uix.label import MDLabel
        from kivy.metrics import dp

        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        next_week = today + timedelta(days=7)

        box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=[dp(16), dp(16), dp(16), dp(12)],
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))

        title_lbl = MDLabel(
            text="Chọn ngày nhắc",
            bold=True,
            font_size="18sp",
            size_hint_y=None,
            height=dp(24),
        )
        box.add_widget(title_lbl)

        def add_option(text, date_obj):
            btn = MDButton(
                MDButtonText(
                    text=text,
                    theme_text_color="Custom",
                    text_color=self.on_surface if hasattr(self, "on_surface") else (0, 0, 0, 1),
                ),
                style="text",
                theme_bg_color="Custom",
                md_bg_color=(0, 0, 0, 0),
                size_hint_y=None,
                height=dp(40),
                on_release=lambda *_: (callback(date_obj), dialog.dismiss()),
            )
            box.add_widget(btn)

        add_option(f"Hôm nay ({today.strftime('%d/%m')})", today)
        add_option(f"Ngày mai ({tomorrow.strftime('%d/%m')})", tomorrow)
        add_option(f"Tuần sau ({next_week.strftime('%d/%m')})", next_week)

        # nút Huỷ
        btn_cancel = MDButton(
            MDButtonText(
                text="HUỶ",
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1),
            ),
            style="elevated",
            theme_bg_color="Custom",
            md_bg_color=self.primary_teal if hasattr(self, "primary_teal") else (0.39, 0.74, 0.67, 1),
            size_hint_y=None,
            height=dp(40),
            on_release=lambda *_: dialog.dismiss(),
        )
        box.add_widget(btn_cancel)

        content = MDDialogContentContainer(box)
        dialog = MDDialog(content)
        dialog.radius = [dp(18)]
        dialog.size_hint = (0.9, None)

        def _autofit(*_):
            dialog.height = min(dp(360), box.height + dp(40))

        from kivy.clock import Clock
        Clock.schedule_once(_autofit, 0)

        dialog.open()

class CalendarDatePicker(MDDialog):
    """
    DatePicker dạng lịch đầy đủ, không cần MDDatePicker.
    callback(date_obj) sẽ trả về datetime.date.
    """

    def __init__(self, callback, **kwargs):
        from kivy.metrics import dp
        from kivy.uix.gridlayout import GridLayout
        from kivymd.uix.label import MDLabel
        from kivymd.uix.button import MDButton, MDButtonText

        self.callback = callback
        super().__init__(**kwargs)

        from datetime import datetime
        today = datetime.now()
        self.year = today.year
        self.month = today.month

        # ===== Header =====
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None, height=dp(42),
            padding=[dp(12), 0, dp(12), 0],
        )

        prev_btn = MDButton(
            MDButtonText(text="<"),
            style="text",
            on_release=lambda *_: self.change_month(-1)
        )
        next_btn = MDButton(
            MDButtonText(text=">"),
            style="text",
            on_release=lambda *_: self.change_month(1)
        )

        self.month_lbl = MDLabel(
            text=self._month_name(self.month) + f" {self.year}",
            halign="center", font_size="17sp", bold=True
        )

        header.add_widget(prev_btn)
        header.add_widget(self.month_lbl)
        header.add_widget(next_btn)

        # ===== Calendar grid =====
        self.grid = GridLayout(cols=7, spacing=dp(4), padding=[dp(10), dp(8)])

        # build calendar
        self._build_calendar()

        # ===== Buttons =====
        btn_cancel = MDButton(
            MDButtonText(text="HUỶ"),
            style="text",
            on_release=lambda *_: self.dismiss()
        )

        content = MDBoxLayout(
            orientation="vertical",
            spacing=dp(6),
            padding=[0, dp(10), 0, dp(4)]
        )
        content.add_widget(header)
        content.add_widget(self.grid)

        box = MDDialogContentContainer(content)

        self.add_widget(box)
        self.add_widget(
            MDDialogButtonContainer(btn_cancel)
        )

        self.size_hint = (0.92, None)
        self.height = dp(420)
        self.radius = [dp(18)]

    # -----------------------------
    def _month_name(self, m):
        return ["", "Tháng 1","Tháng 2","Tháng 3","Tháng 4","Tháng 5","Tháng 6",
                "Tháng 7","Tháng 8","Tháng 9","Tháng 10","Tháng 11","Tháng 12"][m]

    # -----------------------------
    def change_month(self, diff):
        import calendar
        self.month += diff
        if self.month <= 0:
            self.month = 12
            self.year -= 1
        if self.month >= 13:
            self.month = 1
            self.year += 1

        self.month_lbl.text = self._month_name(self.month) + f" {self.year}"
        self._build_calendar()

    # -----------------------------
    def _build_calendar(self):
        import calendar
        from datetime import date
        from kivy.metrics import dp
        from kivymd.uix.button import MDButton, MDButtonText

        self.grid.clear_widgets()

        # Header of week
        for d in ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]:
            self.grid.add_widget(MDLabel(text=d, halign="center", bold=True, font_size="14sp"))

        # Calculate days matrix
        first_weekday, days_in_month = calendar.monthrange(self.year, self.month)
        # convert first_weekday: Mon=0 → Mon=0 (OK)

        for _ in range(first_weekday):
            self.grid.add_widget(Widget())

        for day in range(1, days_in_month + 1):
            btn = MDButton(
                MDButtonText(text=str(day)),
                style="text",
                size_hint_y=None, height=dp(36),
                on_release=lambda _, d=day: self._select_day(d)
            )
            self.grid.add_widget(btn)

    # -----------------------------
    def _select_day(self, day):
        from datetime import date
        self.callback(date(self.year, self.month, day))
        self.dismiss()

class NoteItem(MDCard):
    note_id = StringProperty("")
    title = StringProperty("")
    content = StringProperty("")
    reminder_text = StringProperty("")

# ============================== ĐIỂM VÀO CHƯƠNG TRÌNH ==============================
if __name__ == "__main__":
    print("Đang chạy ứng dụng HS_23VT...")
    uid = sign_in_anonymous()   
    set_uid(uid)                
    HS23VTApp().run()