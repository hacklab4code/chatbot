"""Client HTTP verso il backend (unico canale di comunicazione con il BE)."""
import httpx


class BackendError(Exception):
    """Errore di comunicazione con il BE, con messaggio adatto all'utente."""


class BackendClient:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 300):
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(base_url=self.base_url, headers=self.headers,
                                  timeout=httpx.Timeout(timeout, connect=5))

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            r = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise BackendError("Il servizio di prenotazione sta impiegando troppo tempo. Riprovi tra poco.") from None
        except httpx.HTTPError:
            raise BackendError("Servizio di prenotazione non raggiungibile. Riprovi tra poco.") from None
        if r.status_code == 401:
            raise BackendError("Configurazione errata: chiave di accesso al servizio non valida.")
        if r.status_code == 503:
            raise BackendError("L'assistente è momentaneamente non disponibile. Riprovi tra poco.")
        if r.status_code >= 400:
            raise BackendError(f"Errore del servizio di prenotazione ({r.status_code}).")
        return r.json()

    def chat(self, session_id: str, message: str, channel: str) -> dict:
        return self._request("POST", "/api/v1/chat",
                             json={"session_id": session_id, "message": message, "channel": channel})

    def reset(self, session_id: str) -> dict:
        return self._request("DELETE", f"/api/v1/chat/{session_id}")

    def health(self) -> dict:
        return self._request("GET", "/health")

    def info(self) -> dict:
        return self._request("GET", "/api/v1/info")

    def menu(self, category: str = None, diet: str = None) -> dict:
        params = {}
        if category:
            params["category"] = category
        if diet:
            params["diet"] = diet
        return self._request("GET", "/api/v1/menu", params=params)

    def reservation(self, code: str) -> dict:
        return self._request("GET", f"/api/v1/reservations/{code}")
