import os, time, json, requests
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=False)

API_KEY = os.getenv("FIREBASE_WEB_API_KEY")

_ID_TOKEN = None
_REFRESH_TOKEN = None
_TOKEN_EXP = 0
_LOCAL_ID = None

# nơi lưu token
AUTH_FILE = os.path.join(os.path.dirname(__file__), "..", "auth.json")


# ===== LOCAL SAVE / LOAD =====
def _save_tokens(id_token, refresh_token, local_id, expires_in):
    global _ID_TOKEN, _REFRESH_TOKEN, _LOCAL_ID, _TOKEN_EXP

    _ID_TOKEN = id_token
    _REFRESH_TOKEN = refresh_token
    _LOCAL_ID = local_id
    _TOKEN_EXP = int(time.time()) + int(expires_in) - 30

    data = {
        "id_token": _ID_TOKEN,
        "refresh_token": _REFRESH_TOKEN,
        "local_id": _LOCAL_ID,
        "token_exp": _TOKEN_EXP,
    }

    try:
        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except:
        pass


def _load_tokens():
    global _ID_TOKEN, _REFRESH_TOKEN, _LOCAL_ID, _TOKEN_EXP
    if not os.path.exists(AUTH_FILE):
        return False
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _ID_TOKEN = data.get("id_token")
        _REFRESH_TOKEN = data.get("refresh_token")
        _LOCAL_ID = data.get("local_id")
        _TOKEN_EXP = data.get("token_exp", 0)
        return True
    except:
        return False


# ===== REFRESH =====
def _refresh(refresh_token):
    url = f"https://securetoken.googleapis.com/v1/token?key={API_KEY}"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    r = requests.post(url, data=payload, timeout=8)
    r.raise_for_status()
    j = r.json()

    _save_tokens(
        j["id_token"],
        j["refresh_token"],
        j["user_id"],
        j.get("expires_in", 3600)
    )
    return j


# ===== SIGN IN (AUTO REUSE) =====
def sign_in_anonymous():
    global _ID_TOKEN, _REFRESH_TOKEN, _LOCAL_ID, _TOKEN_EXP

    # 1. load token cũ nếu có
    _load_tokens()

    # nếu có refresh_token → lấy idToken mới
    if _REFRESH_TOKEN:
        try:
            j = _refresh(_REFRESH_TOKEN)
            return j["user_id"]
        except:
            pass   # nếu lỗi → tạo acc mới

    # 2. tạo tài khoản anonymous mới
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}"
    r = requests.post(url, json={"returnSecureToken": True}, timeout=8)
    r.raise_for_status()
    j = r.json()

    _save_tokens(
        j["idToken"],
        j["refreshToken"],
        j["localId"],
        j.get("expiresIn", 3600)
    )
    return j["localId"]


# ===== LẤY TOKEN DÙNG CHO FirebaseClient =====
def get_id_token():
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXP
    _load_tokens()

    if not _ID_TOKEN:
        return None

    # cần refresh?
    if time.time() >= _TOKEN_EXP:
        if _REFRESH_TOKEN:
            _refresh(_REFRESH_TOKEN)

    return _ID_TOKEN


def get_local_id():
    _load_tokens()
    return _LOCAL_ID
