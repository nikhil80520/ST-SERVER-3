"""
Application configuration with validation and service grouping.
"""
import os
from typing import List, Optional
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class FirebaseConfig(BaseSettings):
    """Firebase configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    credentials_path: str = "./firebase-credentials.json"
    storage_bucket: str = ""
    web_api_key: str = ""
    
    @field_validator("credentials_path")
    @classmethod
    def validate_credentials_path(cls, v: str) -> str:
        if not os.path.exists(v):
            raise ValueError(f"Firebase credentials file not found: {v}")
        return v


class DatabaseConfig(BaseSettings):
    """PostgreSQL database configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    url: str = ""
    pool_size: int = 20
    pool_max_overflow: int = 10
    echo: bool = False  # Enable SQL query logging for debugging
    
    @field_validator("url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if v and not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string (postgresql:// or postgresql+asyncpg://)")
        return v


class MinIOConfig(BaseSettings):

    """MinIO storage configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    endpoint: str = "http://34.42.234.149:9000"
    root_user: str = "YOURACCESS"
    root_password: str = "YOURSECRET"
    bucket: str = "media"


class AIServiceConfig(BaseSettings):
    """AI service API keys configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    openai_api_key: str = ""
    groq_api_key: str = ""
    replicate_api_token: str = ""
    deepimage_api_key: str = ""
    deepai_api_key: str = ""
    cartesia_api_key: str = ""
    deepgram_api_key: str = ""
    freesound_api_key: str = ""
    
    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_key(cls, v: str) -> str:
        if not v or v == "test":
            raise ValueError("OpenAI API key is required for story generation")
        return v


class JWTConfig(BaseSettings):
    """JWT authentication configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    private_key_path: str = "./keys/app-jwt.pem"
    public_key_path: str = "./keys/app-jwt.pub"
    device_private_key_path: str = "./keys/device-jwt.pem"
    device_public_key_path: str = "./keys/device-jwt.pub"


class IoTSecurityConfig(BaseSettings):
    """IoT device security configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    hmac_tolerance_seconds: int = 300
    claim_token_ttl_seconds: int = 600  # 10 minutes
    device_jwt_ttl_seconds: int = 14400  # 4 hours
    local_token_ttl_seconds: int = 300  # 5 minutes
    device_secret_key: str = "change-this-secret-key-in-production"
    
    @field_validator("device_secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if v == "change-this-secret-key-in-production" and os.getenv("ENV") == "production":
            raise ValueError("Device secret key must be changed in production")
        return v


class MQTTConfig(BaseSettings):
    """MQTT broker configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    broker_host: str = "localhost"
    broker_port: int = 1883
    username: str = ""
    password: str = ""
    enabled: bool = True


class StoryConfig(BaseSettings):
    """Story generation configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    max_scenes: int = 5
    audio_format: str = "ogg"
    image_size: str = "1290x2796"
    replicate_generation_size: str = "768x768"
    llm_model: str = "gpt-4o-mini"


class PerformanceConfig(BaseSettings):
    """Performance optimization configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    max_concurrent_scenes: int = 4
    max_concurrent_tasks: int = 20
    background_workers: int = 8
    enable_batch_audio: bool = True
    enable_batch_images: bool = True
    enable_parallel_uploads: bool = True
    parallel_audio_generation: bool = True
    parallel_image_generation: bool = True
    parallel_upload_enabled: bool = True
    retry_attempts: int = 3
    operation_timeout: int = 30
    audio_generation_timeout: int = 30
    batch_audio_timeout: int = 120
    image_generation_timeout: int = 60
    batch_image_timeout: int = 300
    upload_timeout: int = 30
    parallel_upload_timeout: int = 60


class AudioConfig(BaseSettings):
    """Audio enhancement configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    enable_ambient_persistence: bool = False
    ambient_cache_dir: str = "./cache/ambient"
    ambient_cache_max_entries: int = 100
    reuse_single_ambient_bed: bool = False
    enable_audio_enhancement: bool = True


class EmailConfig(BaseSettings):
    """Email configuration group."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    enabled: bool = False
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    from_email: str = ""
    from_name: str = "StoryTeller App"


class AWSConfig(BaseSettings):
    """AWS services configuration group."""
    model_config = SettingsConfigDict(
        env_prefix="AWS_",  # Read AWS_* environment variables
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    region: str = "us-east-1"
    access_key_id: str = ""
    secret_access_key: str = ""
    s3_bucket_name: str = ""  # Added for S3 storage
    sqs_queue_url: str = ""
    lambda_function_name: str = "story-generation-worker"
    use_sqs_lambda: bool = False  # Feature flag to switch between local workers and SQS+Lambda


class Settings(BaseSettings):
    """Main application settings with service-grouped configuration."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="allow"
    )

    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    
    # Service-specific configurations
    database: DatabaseConfig = DatabaseConfig()
    firebase: FirebaseConfig = FirebaseConfig()
    minio: MinIOConfig = MinIOConfig()
    ai_services: AIServiceConfig = AIServiceConfig()
    jwt: JWTConfig = JWTConfig()
    iot_security: IoTSecurityConfig = IoTSecurityConfig()
    mqtt: MQTTConfig = MQTTConfig()
    story: StoryConfig = StoryConfig()
    performance: PerformanceConfig = PerformanceConfig()
    audio: AudioConfig = AudioConfig()
    email: EmailConfig = EmailConfig()
    aws: AWSConfig = AWSConfig()
    
    # Legacy flat fields (for backward compatibility)
    database_url: str = ""
    db_pool_size: int = 20
    db_pool_max_overflow: int = 10
    db_echo: bool = False
    firebase_credentials_path: Optional[str] = "./firebase-credentials.json"
    firebase_storage_bucket: str = ""
    firebase_web_api_key: str = ""
    minio_endpoint: str = "http://34.42.234.149:9000"
    minio_root_user: str = "YOURACCESS"
    minio_root_password: str = "YOURSECRET"
    minio_bucket: str = "media"
    jwt_private_key_path: str = "./keys/app-jwt.pem"
    jwt_public_key_path: str = "./keys/app-jwt.pub"
    device_jwt_private_key_path: str = "./keys/device-jwt.pem"
    device_jwt_public_key_path: str = "./keys/device-jwt.pub"
    hmac_tolerance_seconds: int = 300
    claim_token_ttl_seconds: int = 600
    device_jwt_ttl_seconds: int = 14400
    local_token_ttl_seconds: int = 300
    device_secret_key: str = "change-this-secret-key-in-production"
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_enabled: bool = True
    mqtt_username: str = ""
    mqtt_password: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    replicate_api_token: str = ""
    deepimage_api_key: str = ""
    deepai_api_key: str = ""
    elevenlabs_api_key: str = ""  # DEPRECATED
    cartesia_api_key: str = ""
    deepgram_api_key: str = ""
    freesound_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    max_scenes: int = 5
    audio_format: str = "ogg"
    image_size: str = "1290x2796"
    replicate_generation_size: str = "768x768"
    max_concurrent_scenes: int = 4
    max_concurrent_tasks: int = 20
    background_workers: int = 8
    enable_batch_audio: bool = True
    enable_batch_images: bool = True
    enable_parallel_uploads: bool = True
    parallel_audio_generation: bool = True
    parallel_image_generation: bool = True
    parallel_upload_enabled: bool = True
    retry_attempts: int = 3
    operation_timeout: int = 30
    audio_generation_timeout: int = 30
    batch_audio_timeout: int = 120
    image_generation_timeout: int = 60
    batch_image_timeout: int = 300
    upload_timeout: int = 30
    parallel_upload_timeout: int = 60
    enable_ambient_persistence: bool = False
    ambient_cache_dir: str = "./cache/ambient"
    ambient_cache_max_entries: int = 100
    reuse_single_ambient_bed: bool = False
    enable_audio_enhancement: bool = True
    email_enabled: bool = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
    # smtp_server: str = "smtp.gmail.com"
    # smtp_port: int = 587
    # smtp_username: str = ""
    # smtp_password: str = ""
    from_email: str = os.getenv("FROM_EMAIL", "")
    from_name: str = "StoryTeller App"
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    verbose_logging: bool = False
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
    app_deep_link_base: str = os.getenv("APP_DEEP_LINK_BASE", "storymagic://share/")
    allow_local_auth_bypass: bool = False
    
    # CORS settings
    cors_origins: str = "*"
    
    # System prompt
    default_system_prompt: str = """You are a creative children's storyteller specializing in creating completely safe, educational, and fun stories for children aged 4-10. 

    CRITICAL SAFETY REQUIREMENTS:
    - Create only wholesome, positive, and age-appropriate content
    - NO violence, scary themes, dangerous activities, or inappropriate content
    - Focus on friendship, kindness, learning, family, nature, and positive adventures
    - Use simple, clear language that children can understand
    - Promote positive values like sharing, helping others, and being kind

    STORY STRUCTURE:
    - Structure your story into clear scenes (2-5 scenes total)
    - Each scene should be 2-3 sentences long and paint a vivid, safe picture
    - End with a positive message or lesson

    VISUAL PROMPT GUIDELINES (VERY IMPORTANT):
    - Create visual descriptions that are completely child-safe and innocent
    - Use bright, colorful, cartoon-like imagery suitable for children's books
    - Focus on cute animals, friendly characters, beautiful landscapes, toys, or magical but safe scenarios
    - Avoid any content that could be interpreted as scary, violent, or inappropriate
    - Use descriptive words like: cheerful, bright, colorful, friendly, cute, magical, happy, peaceful
    - Examples: "A happy bunny playing in a sunny meadow with colorful flowers"
    - Ensure all characters and scenes are clearly child-appropriate and wholesome

    Remember: Every word and image description must pass the highest child safety standards."""
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Convert cors_origins string to list with React Native defaults."""
        react_native_origins = [
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:19006",
            "http://127.0.0.1:19006",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ]
        
        if self.cors_origins == "*":
            return ["*"]
        
        custom_origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        all_origins = list(set(react_native_origins + custom_origins))
        
        if "*" in all_origins:
            return ["*"]
        
        return all_origins
    
    @property
    def effective_image_size(self) -> str:
        """Get effective image size - use 1290x2796 for optimized portrait format."""
        return "1290x2796"
    
    @model_validator(mode='after')
    def validate_settings(self):
        """Validate settings after initialization."""
        # Validate required API keys for production
        if not self.debug and not self.openai_api_key:
            raise ValueError("OpenAI API key is required in production mode")
        
        # Validate Firebase credentials exist (optional, for Storage only)
        if self.firebase_credentials_path and os.path.exists(self.firebase_credentials_path):
            pass  # Firebase is optional now, only used for Storage
        
        return self


# Create singleton settings instance
settings = Settings()
