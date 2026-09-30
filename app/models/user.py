from dataclasses import dataclass


@dataclass
class User:
    id: str
    password_hash: str
    email: str | None = None
    role: str | None = None
    status: str | None = "active"
