"""Project-local configuration; no network bind override."""
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

ROOT = Path(__file__).resolve().parents[2]

class PositionQualityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    interval_seconds: int = Field(default=60, ge=60, le=300)
    retention_hours: int = Field(default=72, ge=50, le=168)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    port: int = Field(default=8765, ge=1024, le=65535)
    timeout_seconds: int = Field(default=20, ge=1, le=120)
    max_response_bytes: int = Field(default=10_000_000, ge=1024, le=20_000_000)
    position_quality: PositionQualityConfig = Field(default_factory=PositionQualityConfig)
    sources: dict = Field(default_factory=dict)

    @field_validator('sources')
    @classmethod
    def protect_firms_key(cls, value):
        value = {key: dict(settings) for key, settings in value.items()}
        for source, field in [('firms', 'map_key'), ('tomtom', 'api_key'), ('ships', 'api_key'),
                              ('buses_warsaw', 'api_key'), ('sentinel2', 'client_id'), ('sentinel2', 'client_secret'),
                              ('sentinel5p', 'client_id'), ('sentinel5p', 'client_secret')]:
            if value.get(source, {}).get(field):
                key = value[source][field]
                value[source][field] = key if isinstance(key, SecretStr) else SecretStr(str(key))
        return value

    def ioda_asns(self):
        return [str(code) for code in self.sources.get('ioda', {}).get('asns', [5617,12741,12912])]

    @field_validator('sources')
    @classmethod
    def validate_ioda(cls, value):
        settings = value.get('ioda', {})
        codes = settings.get('asns', [5617,12741,12912])
        if not isinstance(codes, list) or len(codes)>8 or len({str(c) for c in codes}) != len(codes):
            raise ValueError('IODA: maksymalnie 8 unikalnych ASN')
        if any(not str(c).isdigit() or not 0<int(c)<=4294967295 for c in codes):
            raise ValueError('IODA: nieprawidłowy numer ASN')
        if settings.get('interval_seconds',300) not in (300,600):
            raise ValueError('IODA: interwał 300 albo 600 sekund')
        return value

    def firms_key(self):
        key = self.sources.get('firms', {}).get('map_key')
        return key.get_secret_value().strip() if isinstance(key, SecretStr) else ''

    def tomtom_key(self):
        key = self.sources.get('tomtom', {}).get('api_key')
        return key.get_secret_value().strip() if isinstance(key, SecretStr) else ''

    def ships_key(self):
        key = self.sources.get('ships', {}).get('api_key')
        return key.get_secret_value().strip() if isinstance(key, SecretStr) else ''

    def warsaw_key(self):
        key = self.sources.get('buses_warsaw', {}).get('api_key')
        return key.get_secret_value().strip() if isinstance(key, SecretStr) else ''

    @classmethod
    def load(cls, root=ROOT):
        file = root / 'config.local.toml'
        data=tomllib.loads(file.read_text()) if file.exists() else {}
        data.pop('llm',None)  # Read legacy configs without restoring removed model calls.
        return cls.model_validate(data)

    def interval(self, source, default):
        return max(default, int(self.sources.get(source, {}).get('interval_seconds', default)))

    def enabled(self, source):
        return bool(self.sources.get(source, {}).get('enabled', True))
