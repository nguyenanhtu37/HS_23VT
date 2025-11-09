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
from features.notifications import ReminderNotifier
from kivymd.app import MDApp
from kivymd.uix.dialog import (MDDialog, MDDialogContentContainer, MDDialogButtonContainer)
from kivymd.uix.menu import MDDropdownMenu
from kivymd.uix.button import MDButton, MDButtonText
from kivymd.uix.textfield import MDTextField
from kivymd.uix.pickers import MDTimePickerDialVertical
from kivymd.uix.label import MDLabel
from kivymd.uix.fitimage import FitImage
from data.firebase_db import (add_class_fb, get_schedule_by_day, delete_class_fb, update_class_fb, get_today_schedule)
from features.timetable import normalize_day
from utils.constants import DAY_LABEL, DAY_ORDER
from utils.validators import is_valid_time, to_int

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

        self.morning_list    = ids.morning_list
        self.afternoon_list  = ids.afternoon_list
        self.morning_title   = ids.morning_title
        self.afternoon_title = ids.afternoon_title

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
            self.show_message(f"Khoảng thời gian này bị trùng với \"{other_subj}\" ({other_t}).")
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
            self.show_message(f"Khoảng thời gian này bị trùng với \"{other_subj}\" ({other_t}).")
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
        if self.screen.ids.sm.current == "timetable":
            self.show_add_class_dialog()

    # ------------------------------ Điều hướng có hiệu ứng ripple ------------------------------
    def nav_after_ripple(self, name: str):
        self.current_section = name
        if name == "timetable":
            self.show_timetable()
        Clock.schedule_once(lambda *_: self.close_drawer(), 0.18)

    def nav_and_close(self, name: str):
        self.current_section = name
        if name == "timetable":
            self.show_timetable()
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

# ============================== ĐIỂM VÀO CHƯƠNG TRÌNH ==============================
if __name__ == "__main__":
    print("Đang chạy ứng dụng HS_23VT...")
    HS23VTApp().run()