"""Application configuration using Pydantic Settings"""
from typing import List, Optional
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    APP_NAME: str = "Vendor Onboarding & Risk Orchestrator"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "postgresql://vendoruser:vendorpass@postgres:5432/vendordb"

    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    API_KEY_HEADER: str = "X-API-Key"
    API_KEYS: str = "demo-api-key-001,demo-api-key-002"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # AI Provider
    LLM_PROVIDER: str = "mock"  # openai | mock
    OPENAI_API_KEY: Optional[str] = None
    # Leave unset to use api.openai.com. Set it to point at any
    # OpenAI-compatible endpoint, e.g. http://localhost:20128/v1
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_MAX_RETRIES: int = 3
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_TEMPERATURE: float = 0.1

    # Document processing
    DOCUMENT_STORAGE_PATH: str = "/app/documents/uploads"
    MAX_UPLOAD_SIZE_MB: int = 25
    ALLOWED_MIME_TYPES: str = "application/pdf,text/plain,text/csv,application/json,image/png,image/jpeg"

    # Confidence thresholds (prototype defaults - configurable)
    CONFIDENCE_HIGH: float = 0.90
    CONFIDENCE_MEDIUM: float = 0.75

    # Risk scoring weights (points)
    RISK_WEIGHT_MISSING_DOCUMENT: int = 15
    RISK_WEIGHT_EXPIRED_DOCUMENT: int = 25
    RISK_WEIGHT_EXPIRING_SOON: int = 10
    RISK_WEIGHT_ENTITY_MISMATCH: int = 20
    RISK_WEIGHT_BANKING_MISMATCH: int = 30
    RISK_WEIGHT_LOW_CONFIDENCE: int = 8
    RISK_WEIGHT_HIGH_RISK_GEOGRAPHY: int = 15
    RISK_WEIGHT_INCOMPLETE_OWNERSHIP: int = 15
    RISK_WEIGHT_AI_UNCERTAINTY: int = 12

    # Risk level thresholds
    RISK_THRESHOLD_LOW: int = 25
    RISK_THRESHOLD_MEDIUM: int = 50
    RISK_THRESHOLD_HIGH: int = 75

    # Rule engine
    RULE_INSURANCE_MIN_COVERAGE: int = 2_000_000  # USD
    RULE_INSURANCE_EXPIRY_WARNING_DAYS: int = 30
    RULE_VENDOR_NAME_SIMILARITY_THRESHOLD: float = 0.92
    RULE_AUTO_APPROVE_MAX_RISK: int = 25

    # n8n
    N8N_WEBHOOK_URL: str = "http://n8n:5678"
    N8N_API_KEY: str = "n8n-api-key"

    # Mock services
    ERP_API_URL: str = "http://mock-erp:8001"
    COMPLIANCE_API_URL: str = "http://mock-compliance:8002"
    NOTIFICATION_API_URL: str = "http://mock-notifications:8003"

    # Observability
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def api_keys_list(self) -> List[str]:
        return [k.strip() for k in self.API_KEYS.split(",") if k.strip()]

    @property
    def allowed_mime_types_list(self) -> List[str]:
        return [m.strip() for m in self.ALLOWED_MIME_TYPES.split(",") if m.strip()]


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance"""
    return Settings()


settings = get_settings()
