from requests import exceptions as req_exc
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from data.services.firebase_client import firebase
from utils.days import normalize_day
from utils.constants import DAY_ORDER
from app_state import get_uid

def _user_path(*segments: str) -> str:
    uid = get_uid()
    if not uid:
        raise RuntimeError("UID is not set. Call sign_in_anonymous() before using firebase_db.")
    return "/".join(["users", uid, *[s.strip("/") for s in segments]])

# ===== Utils =====
def _sort_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

def add_class_fb(subject: str, period: int, time_str: str, end_str: str, day_text: str, room: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    day = normalize_day(day_text)
    data: Dict[str, Any] = {"subject": subject, "period": int(period), "time": time_str, "end": end_str}
    if room:
        data["room"] = room
    try:
        res = firebase.post(_user_path("timetable", day), json=data)
        new_id = (res or {}).get("name")
        print(f"[Timetable] + {subject} (Tiết {period}, {time_str}-{end_str}) → {day} | id={new_id}")
        return True, new_id
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi khi lưu:", e)
        return False, None

def get_schedule_by_day(day_text: str) -> List[Dict[str, Any]]:
    day = normalize_day(day_text)
    try:
        data = firebase.get(_user_path("timetable", day)) or {}
        items = [{"id": k, **v} for k, v in data.items()] if isinstance(data, dict) else []
        return _sort_items(items)
    except req_exc.RequestException as e:
        print("[Timetable] Lỗi tải:", e)
        return []

def delete_class_fb(day_text: str, class_id: str) -> bool:
    day = normalize_day(day_text)
    try:
        firebase.delete(_user_path("timetable", day, class_id))
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
    room: Optional[str] = None,
    keep_id_when_move: bool = True,
) -> bool:
    old_day = normalize_day(old_day_text)
    new_day = normalize_day(new_day_text)
    data: Dict[str, Any] = {"subject": subject, "period": int(period), "time": time_str, "end": end_str}
    if room:
        data["room"] = room
    try:
        if old_day == new_day:
            firebase.patch(_user_path("timetable", old_day, class_id), json=data)
            print(f"[Timetable] ~ update id={class_id} @ {old_day}")
            return True

        if keep_id_when_move:
            firebase.put(_user_path("timetable", new_day, class_id), json=data)
            firebase.delete(_user_path("timetable", old_day, class_id))
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
    idx = datetime.today().weekday()  # 0=Mon..6=Sun
    day = DAY_ORDER[idx]
    return day, get_schedule_by_day(day)

def get_week_schedule():
    week: Dict[str, List[Dict[str, Any]]] = {d: [] for d in DAY_ORDER}
    try:
        data = firebase.get(_user_path("timetable")) or {}
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

# ===== Notes (Firebase) =====

def add_note_fb(title: str, content: str, reminder_at: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    try:
        data: Dict[str, Any] = {
            "title": title or "",
            "content": content or "",
            "created_at": datetime.utcnow().isoformat(),
        }
        if reminder_at:
            data["reminder_at"] = reminder_at

        res = firebase.post(_user_path("notes"), json=data)
        new_id = (res or {}).get("name")
        print(f"[Notes] + {title} -> id={new_id}")
        return True, new_id
    except req_exc.RequestException as e:
        print("[Notes] Lỗi khi lưu:", e)
        return False, None

def get_notes() -> List[Dict[str, Any]]:
    try:
        data = firebase.get(_user_path("notes")) or {}

        print("[get_notes] raw data from Firebase:", data)
        
        items = [{"id": k, **v} for k, v in (data.items() if isinstance(data, dict) else [])]
        # sort newest first by created_at if present
        try:
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception:
            pass

        print("[get_notes] mapped items:", items)

        return items
    except req_exc.RequestException as e:
        print("[Notes] Lỗi tải:", e)
        return []

def update_note_fb(
    note_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    reminder_at: Optional[str] = None,
) -> bool:
    try:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if content is not None:
            payload["content"] = content
        if reminder_at is not None:
            payload["reminder_at"] = reminder_at

        if not payload:
            return True

        firebase.patch(_user_path("notes", note_id), json=payload)
        print(f"[Notes] ~ update id={note_id}")
        return True
    except req_exc.RequestException as e:
        print("[Notes] Lỗi cập nhật:", e)
        return False

def delete_note_fb(note_id: str) -> bool:
    try:
        firebase.delete(_user_path("notes", note_id))
        print(f"[Notes] - id={note_id}")
        return True
    except req_exc.RequestException as e:
        print("[Notes] Lỗi xoá:", e)
        return False
