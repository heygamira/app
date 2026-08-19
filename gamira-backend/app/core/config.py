"""Environment-driven settings.

One settings object serves local, test, staging and production. The environment
name only selects defaults; it never unlocks a weaker security path in staging
or production (see ``Settings.model_post_init``).
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
AuthMode = Literal["firebase", "dev"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = "local"
    app_name: str = "Gamira API"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    debug: bool = False

    # postgresql+asyncpg://... in every real environment. The sqlite+aiosqlite
    # form exists so the test suite and a first checkout run without Docker.
    database_url: str = "postgresql+asyncpg://gamira:gamira@localhost:5432/gamira"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_recycle_seconds: int = 1800
    database_echo: bool = False

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:5174"]
    )

    # "dev" accepts locally issued test tokens and is refused outside local/test.
    auth_mode: AuthMode = "dev"
    firebase_project_id: str = ""
    firebase_jwks_url: str = (
        "https://www.googleapis.com/robot/v1/metadata/x509/"
        "securetoken@system.gserviceaccount.com"
    )
    dev_token_prefix: str = "dev:"

    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ----------------------------------------------------------------- #
    # Background worker
    # ----------------------------------------------------------------- #

    # How long a claimed job stays claimed without a heartbeat. A worker killed
    # mid-job releases its work after this, not never.
    worker_lease_seconds: int = 60
    worker_poll_interval_seconds: float = 1.0
    worker_batch_size: int = 8
    worker_concurrency: int = 4
    worker_shutdown_grace_seconds: float = 20.0
    # Whether the worker also enqueues the recurring maintenance ticks. Set to
    # false when Cloud Scheduler drives them instead.
    worker_run_scheduler: bool = True
    worker_scheduler_interval_seconds: float = 30.0

    job_max_attempts: int = 5
    job_retry_base_seconds: float = 5.0
    job_retry_max_seconds: float = 900.0

    # ----------------------------------------------------------------- #
    # Deterministic care rules
    # ----------------------------------------------------------------- #

    # How far ahead dose events are materialised. Long enough that a worker
    # outage of a day does not cost anyone their medicine reminder.
    dose_materialization_days: int = 3
    dose_materialization_backfill_hours: int = 24
    medication_reminder_lead_minutes: int = 0
    # Minutes an SOS may sit unacknowledged before the family is told again.
    sos_escalation_after_minutes: int = 5
    sos_max_escalations: int = 3
    appointment_reminder_lead_hours: int = 24

    # ----------------------------------------------------------------- #
    # Push notifications
    # ----------------------------------------------------------------- #

    # "fake" records the attempt without calling anyone and is the only value
    # the test suite uses. "firebase" needs real credentials.
    fcm_provider: Literal["fake", "firebase"] = "fake"
    fcm_credentials_file: str = ""
    fcm_project_id: str = ""
    fcm_timeout_seconds: float = 10.0

    # ----------------------------------------------------------------- #
    # AI
    # ----------------------------------------------------------------- #

    ai_provider: Literal["fake", "gemini"] = "fake"
    gemini_api_key: str = ""
    # The text layer: chat replies and weekly summaries. Flash Lite is the right
    # size for it — every answer is written from figures the backend already
    # counted, against a schema, with the safety rules in the system prompt, so
    # the work is phrasing rather than reasoning. Measured on the real prompt it
    # answers in about a second and holds the "never say a reading is healthy"
    # line. Note 2.5-flash-lite is closed to new keys; Google's own 404 points
    # here.
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    gemini_live_api_version: str = "v1alpha"
    ai_request_timeout_seconds: float = 30.0
    ai_max_attempts: int = 3
    ai_retry_base_seconds: float = 0.5

    # A Live token is only good to *open* a session for a minute; the session
    # itself then runs for the longer window.
    live_session_ttl_minutes: int = 30
    live_session_open_window_minutes: int = 1
    live_session_max_concurrent: int = 2
    live_sessions_per_hour: int = 20
    # A session opened speculatively by the wake word, before it is sure. It
    # expires quickly if nobody promotes it, and spends no hourly quota — the
    # detector pre-connects far more often than a person actually speaks, and
    # charging for the guesses would exhaust the limit in minutes. The
    # concurrency cap is what stops a looping client minting forever.
    live_provisional_ttl_seconds: int = 120
    live_provisional_max_concurrent: int = 2
    # A ceiling on *guesses*, on the server. The concurrent cap above can never
    # bind — a guess is abandoned after two seconds and the next is five apart —
    # so without this the only limit on how many tokens a noisy room can mint
    # was a constant in the browser. Loose on purpose: a person really talking
    # to Gamira will not come near it.
    live_provisional_per_hour: int = 60
    ai_requests_per_hour: int = 60
    # How long a confirmation prompt stays answerable before it expires.
    ai_confirmation_ttl_seconds: int = 300
    # Quiet hours for anything Gamira volunteers, read in the cared-for
    # person's own timezone. Nothing she raises herself is urgent — the urgent
    # path is an alert, which she cannot raise — so a notice that would land at
    # three in the morning waits until the morning. Set both to the same hour
    # to switch this off.
    family_notice_quiet_start_hour: int = 21
    family_notice_quiet_end_hour: int = 8
    # How long a stored conversation is kept before its transcript is deleted.
    # `retention_policy="transcript_only"` on every conversation has always
    # promised this; this is the number that makes it true. Long enough for a
    # family to look back over a fortnight, short enough that a voice companion
    # is not building an indefinite record of somebody's private talk.
    conversation_retention_days: int = 30
    # How long a flagged reading waits for an answer before the family is told.
    # Long enough that somebody in another room can come back to the phone;
    # short enough to be worth anything at all.
    wellbeing_check_grace_minutes: int = 10

    file_storage_backend: Literal["local", "gcs"] = "local"
    file_storage_dir: str = "./.local-storage"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def model_post_init(self, __context: object) -> None:
        if self.auth_mode == "dev" and self.app_env in ("staging", "production"):
            raise ValueError(
                "AUTH_MODE=dev is refused in staging and production. "
                "Set AUTH_MODE=firebase and FIREBASE_PROJECT_ID."
            )
        if self.auth_mode == "firebase" and not self.firebase_project_id:
            raise ValueError("AUTH_MODE=firebase requires FIREBASE_PROJECT_ID.")
        if self.app_env in ("staging", "production") and self.database_url.startswith(
            "sqlite"
        ):
            raise ValueError("SQLite is not a supported staging or production database.")
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("AI_PROVIDER=gemini requires GEMINI_API_KEY.")
        if self.app_env in ("staging", "production") and self.fcm_provider == "fake":
            raise ValueError(
                "FCM_PROVIDER=fake delivers nothing and is refused outside "
                "local and test. Set FCM_PROVIDER=firebase."
            )

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_local_like(self) -> bool:
        return self.app_env in ("local", "test")


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
