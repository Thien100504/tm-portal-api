import re
from contextvars import ContextVar

# Browser tab that sent the current request (X-Client-Id header). WebSocket
# broadcasts carry it so that tab can skip its own echo while the same user's
# other tabs still refresh.
client_id_var: ContextVar[str | None] = ContextVar("client_id", default=None)

_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def parse_client_id(value: str | None) -> str | None:
    return value if value and _CLIENT_ID.fullmatch(value) else None
