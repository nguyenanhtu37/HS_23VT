_uid = None

def set_uid(uid: str):
    global _uid
    _uid = uid

def get_uid() -> str | None:
    return _uid