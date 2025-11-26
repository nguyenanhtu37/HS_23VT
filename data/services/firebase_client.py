import requests
from data.services.firebase_auth import get_id_token

class FirebaseClient:
    def __init__(self, base_url: str, timeout: int = 6):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        if not path.endswith(".json"):
            path += ".json"
        url = f"{self.base_url}/{path}"
        token = get_id_token()
        if token:
            url += f"?auth={token}"
        return url

    def get(self, path: str):
        r = self.session.get(self._url(path), timeout=self.timeout); r.raise_for_status(); return r.json() or {}
    def post(self, path: str, json: dict):
        r = self.session.post(self._url(path), json=json, timeout=self.timeout); r.raise_for_status(); return r.json() or {}
    def put(self, path: str, json: dict):
        r = self.session.put(self._url(path), json=json, timeout=self.timeout); r.raise_for_status(); return r.json() or {}
    def patch(self, path: str, json: dict):
        r = self.session.patch(self._url(path), json=json, timeout=self.timeout); r.raise_for_status(); return r.json() or {}
    def delete(self, path: str):
        r = self.session.delete(self._url(path), timeout=self.timeout); r.raise_for_status(); return True

firebase = FirebaseClient(base_url="https://hs23vt-default-rtdb.firebaseio.com/", timeout=6)