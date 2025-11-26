from dataclasses import dataclass
from typing import List, Optional
import datetime
from data.firebase_db import (
    add_note_fb,
    get_notes,
    update_note_fb,
    delete_note_fb,
)


@dataclass
class Note:
    id: str
    title: str
    content: str
    created_at: str
    # 👇 thêm field mới
    reminder_at: Optional[str] = None


class NoteManager:
    def __init__(self):
        self._notes: List[Note] = []
        self.load()

    def load(self):
        items = get_notes() or []
        self._notes = []

        print("[NoteManager.load] items from get_notes():")
        for it in items:
            print("   ", it)

        for it in items:
            note = Note(
                id=it.get("id", ""),
                title=it.get("title", ""),
                content=it.get("content", ""),
                created_at=it.get("created_at", ""),
                reminder_at=it.get("reminder_at"),
            )
            self._notes.append(note)

        print("[NoteManager.load] self._notes:")
        for n in self._notes:
            print("   Note(id=%s, title=%s, reminder_at=%s)" % (n.id, n.title, n.reminder_at))

    def list_notes(self) -> List[Note]:
        # luôn load mới rồi trả bản copy
        self.load()
        return list(self._notes)

    def add_note(
        self,
        title: str,
        content: str,
        reminder_at: Optional[str] = None,
    ) -> Optional[Note]:
        """Tạo note mới + lưu reminder_at lên Firebase."""
        title_final = title or "Không có tiêu đề"
        content_final = content or ""

        ok, nid = add_note_fb(title_final, content_final, reminder_at=reminder_at)
        if not ok or not nid:
            return None

        created_at = datetime.datetime.utcnow().isoformat()
        n = Note(
            id=nid,
            title=title_final,
            content=content_final,
            created_at=created_at,
            reminder_at=reminder_at,
        )
        # cập nhật cache: thêm đầu danh sách
        self._notes.insert(0, n)
        return n

    def update_note(
        self,
        nid: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        reminder_at: Optional[str] = None,
    ) -> Optional[Note]:
        """Cập nhật title/content/reminder_at cho note."""
        ok = update_note_fb(
            nid,
            title=title,
            content=content,
            reminder_at=reminder_at,
        )
        if not ok:
            return None

        # update local cache
        for n in self._notes:
            if n.id == nid:
                if title is not None:
                    n.title = title
                if content is not None:
                    n.content = content
                if reminder_at is not None:
                    n.reminder_at = reminder_at
                return n

        # nếu không thấy trong cache thì reload
        self.load()
        return next((x for x in self._notes if x.id == nid), None)

    def delete_note(self, nid: str) -> bool:
        ok = delete_note_fb(nid)
        if ok:
            self._notes = [n for n in self._notes if n.id != nid]
        return ok

    def search_notes(self, query: str) -> List[Note]:
        self.load()
        if not query:
            return list(self._notes)
        q = query.lower()
        return [
            n
            for n in self._notes
            if q in (n.title or "").lower() or q in (n.content or "").lower()
        ]
