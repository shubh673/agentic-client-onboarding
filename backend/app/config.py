from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://onboarding:onboarding@localhost:5433/onboarding"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    CORS_ORIGINS: str = "http://localhost:5173"

    AWS_REGION: str
    AWS_S3_BUCKET: str
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    PRESIGNED_URL_TTL_SECONDS: int = 300

    COGNITO_USER_POOL_ID: str
    COGNITO_CLIENT_ID: str
    COGNITO_CLIENT_SECRET: str

    # OpenSanctions — sanctions + PEP screening (Stage 3 compliance agent).
    # When OPENSANCTIONS_API_KEY is unset the screening node falls back to a
    # dev stub so local runs still flow through; set it to screen for real.
    OPENSANCTIONS_API_KEY: str | None = None
    OPENSANCTIONS_BASE_URL: str = "https://api.opensanctions.org"
    OPENSANCTIONS_DATASET: str = "default"
    OPENSANCTIONS_SCORE_THRESHOLD: float = 0.7
    OPENSANCTIONS_TIMEOUT_S: float = 10.0
    # Second-pass name gate: we re-check the applicant's name against the matched
    # entity's names (subset-aware) and only confirm a hit at/above this score,
    # dropping common-name false positives. A very confident sanction match
    # (>= the force floor) stays flagged regardless, as a safety backstop.
    OPENSANCTIONS_NAME_THRESHOLD: float = 0.80
    OPENSANCTIONS_SANCTION_FORCE_FLOOR: float = 0.90

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def cognito_issuer(self) -> str:
        return f"https://cognito-idp.{self.AWS_REGION}.amazonaws.com/{self.COGNITO_USER_POOL_ID}"

    @property
    def cognito_jwks_url(self) -> str:
        return f"{self.cognito_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
