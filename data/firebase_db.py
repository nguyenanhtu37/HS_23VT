import requests
from requests import exceptions as req_exc
from datetime import datetime
from features.timetable import normalize_day
from utils.constants import DAY_ORDER

FIREBASE_URL = "https://hs23vt-default-rtdb.firebaseio.com/"
TIMEOUT = 6  
_session = requests.Session()


# ===== Utils =====
def _url(path: str) -> str:
    path = path.lstrip('/')
    if not path.endswith('.json'):
        path += '.json'
    return FIREBASE_URL.rstrip('/') + '/' + path

def _sort_items(items):
    def key_fn(x):
        p = x.get("period", 9999)
        t = (x.get("time") or "")
        try:
            h, m = [int(i) for i in (t.split(":") if ":" in t else ["99", "99"])]
        except Exception:
            h, m = (99, 99)
        return (int(p) if isinstance(p, (int, float, str)) and str(p).isdigit() else 9999, h * 60 + m)
    return sorted(items, key=key_fn)


# ===== Timetable (Firebase) =====
# Cấu trúc:
# timetable/<day>/<autoKey> = { subject, period, time, end, room? }

def add_class_fb(subject: str, period: int, time_str: str, end_str: str, day_text: str, room: str | None = None):
    """
    Tạo mới lớp học trong ngày. Trả về (ok: bool, id: str|None).
    Dùng POST để Firebase tạo key tự động.
    """
    day = normalize_day(day_text)
    data = {"subject": subject, "period": int(period), "time": time_str, "end": end_str}
    if room:
        data["room"] = room
    try:
        r = _session.post(_url(f"timetable/{day}"), json=data, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json() or {}
        new_id = res.get("name")
        print(f"[Timetable] + {subject} (Tiết {period}, {time_str}-{end_str}) → {day} | id={new_id}")
        return True, new_id
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi khi lưu:", e)
        return False, None

def get_schedule_by_day(day_text: str):
    """
    Lấy danh sách tiết cho 1 ngày, đã sort (period, time).
    Trả về list[{id, subject, period, time, end, room?}]
    """
    day = normalize_day(day_text)
    try:
        r = _session.get(_url(f"timetable/{day}"), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json() or {}
        items = [{"id": k, **v} for k, v in data.items()] if isinstance(data, dict) else []
        return _sort_items(items)
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi tải:", e)
        return []

def delete_class_fb(day_text: str, class_id: str):
    """
    Xoá 1 tiết theo id trong ngày. Trả về bool.
    """
    day = normalize_day(day_text)
    try:
        r = _session.delete(_url(f"timetable/{day}/{class_id}"), timeout=TIMEOUT)
        r.raise_for_status()
        print(f"[Timetable] - id={class_id} @ {day}")
        return True
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi xoá:", e)
        return False

def update_class_fb(
    class_id: str,
    old_day_text: str,
    *,
    subject: str,
    period: int,
    time_str: str,
    end_str: str,
    new_day_text: str,
    room: str | None = None,
    keep_id_when_move: bool = True,  
):
    """
    Cập nhật tiết học. Nếu đổi ngày:
      - keep_id_when_move=True → PUT vào đường dẫn mới để giữ nguyên id
      - keep_id_when_move=False → DELETE cũ + POST mới (id thay đổi)
    Trả về bool.
    """
    old_day = normalize_day(old_day_text)
    new_day = normalize_day(new_day_text)
    data = {"subject": subject, "period": int(period), "time": time_str, "end": end_str}
    if room:
        data["room"] = room

    try:
        if old_day == new_day:
            r = _session.patch(_url(f"timetable/{old_day}/{class_id}"), json=data, timeout=TIMEOUT)
            r.raise_for_status()
            print(f"[Timetable] ~ update id={class_id} @ {old_day}")
            return True

        if keep_id_when_move:
            r_put = _session.put(_url(f"timetable/{new_day}/{class_id}"), json=data, timeout=TIMEOUT)
            r_put.raise_for_status()
            _session.delete(_url(f"timetable/{old_day}/{class_id}"), timeout=TIMEOUT)
            print(f"[Timetable] ↔ move id={class_id} {old_day} → {new_day}")
            return True
        else:
            del_ok = delete_class_fb(old_day, class_id)
            add_ok, _ = add_class_fb(subject, period, time_str, end_str, new_day, room=room)
            return del_ok and add_ok

    except req_exc.RequestException as e:
        print("[Timetable] Lỗi cập nhật:", e)
        return False

def get_today_schedule():
    """
    Trả về (day_key, items_sorted).
    day_key là tên ngày theo DAY_ORDER, items đã sort.
    """
    idx = datetime.today().weekday()  # 0=Mon..6=Sun
    day = DAY_ORDER[idx]
    return day, get_schedule_by_day(day)

def get_week_schedule():
    """
    Lấy toàn bộ tuần trong 1 request rồi phân loại, giảm số lần gọi mạng.
    Trả về dict[day] = list sorted.
    """
    week = {d: [] for d in DAY_ORDER}
    try:
        r = _session.get(_url("timetable"), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json() or {}
        if isinstance(data, dict):
            for d in DAY_ORDER:
                raw = data.get(d) or {}
                items = [{"id": k, **v} for k, v in raw.items()] if isinstance(raw, dict) else []
                week[d] = _sort_items(items)
        return week
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi tải tuần:", e)
        for d in DAY_ORDER:
            week[d] = get_schedule_by_day(d)
        return week