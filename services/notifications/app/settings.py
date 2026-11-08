import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    issuer: str
    audience: str
    jwks_url: str
    rabbitmq_url: str

    @classmethod
    def from_env(cls):
        required = ("DATABASE_URL", "JWT_ISSUER", "JWT_AUDIENCE", "JWT_JWKS_URL")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError("Missing settings: " + ", ".join(missing))
        return cls(*(os.environ[key] for key in required), os.getenv("RABBITMQ_URL", ""))
