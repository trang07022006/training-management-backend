from dataclasses import dataclass


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    role: str = "user"
    status: str = "active"
