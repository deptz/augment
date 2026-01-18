import os
import yaml
import logging
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from .prompts import Prompts

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for the backfill tool"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # Load .env file (not .env.example - that's just a template)
        env_loaded = load_dotenv()
        if env_loaded:
            logger.info(f"[Config] Loaded .env file from: {os.path.abspath('.env')}")
        else:
            logger.warning("[Config] No .env file found - using environment variables and defaults")
        
        # Log OpenCode-specific env vars for debugging (without exposing values)
        opencode_provider = os.getenv('OPENCODE_LLM_PROVIDER')
        opencode_model = os.getenv('OPENCODE_ANTHROPIC_MODEL')
        if opencode_provider:
            logger.info(f"[Config] OPENCODE_LLM_PROVIDER is set: {opencode_provider}")
        if opencode_model:
            logger.info(f"[Config] OPENCODE_ANTHROPIC_MODEL is set: {opencode_model}")
        elif opencode_provider == 'claude':
            logger.warning("[Config] OPENCODE_ANTHROPIC_MODEL is NOT set but provider is claude - this will cause an error")
        
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file with environment variable substitution"""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as file:
            config_content = file.read()
        
        # Simple environment variable substitution
        config_content = self._substitute_env_vars(config_content)
        
        return yaml.safe_load(config_content)
    
    def _substitute_env_vars(self, content: str) -> str:
        """Replace ${VAR_NAME} and ${VAR_NAME:default} with environment variables"""
        import re
        
        def replace_var(match):
            var_expr = match.group(1)
            if ':' in var_expr:
                var_name, default_value = var_expr.split(':', 1)
                return os.getenv(var_name, default_value)
            else:
                return os.getenv(var_expr, '')
        
        return re.sub(r'\$\{([^}]+)\}', replace_var, content)
    
    @property
    def jira(self) -> Dict[str, Any]:
        return self._config.get('jira', {})
    
    @property
    def bitbucket(self) -> Dict[str, Any]:
        return self._config.get('bitbucket', {})
    
    def get_bitbucket_workspaces(self) -> List[str]:
        """
        Get list of Bitbucket workspaces from configuration.
        
        Supports both 'workspaces' (comma-separated string or list) and 'workspace' (single, backward compatibility).
        Returns empty list if neither is configured.
        """
        bitbucket_config = self.bitbucket
        
        # Try workspaces first (multi-workspace support)
        workspaces = bitbucket_config.get('workspaces', '')
        if workspaces:
            # Handle comma-separated string
            if isinstance(workspaces, str):
                # Split by comma and strip whitespace
                workspaces_list = [w.strip() for w in workspaces.split(',') if w.strip()]
                if workspaces_list:
                    return workspaces_list
            # Handle list
            elif isinstance(workspaces, list):
                # Filter out empty strings
                workspaces_list = [w for w in workspaces if w and isinstance(w, str)]
                if workspaces_list:
                    return workspaces_list
        
        # Fallback to single workspace (backward compatibility)
        workspace = bitbucket_config.get('workspace', '')
        if workspace and isinstance(workspace, str) and workspace.strip():
            return [workspace.strip()]
        
        return []
    
    @property
    def confluence(self) -> Dict[str, Any]:
        return self._config.get('confluence', {})
    
    @property
    def llm(self) -> Dict[str, Any]:
        return self._config.get('llm', {})
    
    @property
    def processing(self) -> Dict[str, Any]:
        return self._config.get('processing', {})
    
    def get_max_tasks_per_story(self) -> int:
        """Get maximum tasks per story from environment or config"""
        return int(os.getenv('MAX_TASKS_PER_STORY', self.processing.get('max_tasks_per_story', 10)))
    
    @property
    def prompts(self) -> Dict[str, Any]:
        return self._config.get('prompts', {})
    
    @property
    def auth(self) -> Dict[str, Any]:
        return self._config.get('auth', {})
    
    @property
    def cors(self) -> Dict[str, Any]:
        return self._config.get('cors', {})
    
    @property
    def opencode(self) -> Dict[str, Any]:
        """OpenCode execution engine configuration"""
        return self._config.get('opencode', {})
    
    @property
    def git(self) -> Dict[str, Any]:
        """Git credentials configuration for repo cloning"""
        return self._config.get('git', {})
    
    def is_opencode_enabled(self) -> bool:
        """Check if OpenCode integration is enabled"""
        return self.opencode.get('enabled', False)
    
    def get_opencode_config(self) -> Dict[str, Any]:
        """Get OpenCode configuration with defaults"""
        opencode_config = self.opencode
        return {
            'enabled': opencode_config.get('enabled', False),
            'docker_image': opencode_config.get('docker_image', 'ghcr.io/anomalyco/opencode'),
            'max_concurrent': int(opencode_config.get('max_concurrent', 2)),
            'max_repos_per_job': int(opencode_config.get('max_repos_per_job', 5)),
            'job_timeout_minutes': int(opencode_config.get('job_timeout_minutes', 20)),
            'clone_timeout_seconds': int(opencode_config.get('clone_timeout_seconds', 300)),
            'shallow_clone': opencode_config.get('shallow_clone', True),
            'result_file': opencode_config.get('result_file', 'result.json'),
            'max_result_size_mb': int(opencode_config.get('max_result_size_mb', 10)),
            'debug_conversation_logging': opencode_config.get('debug_conversation_logging', False),
            'conversation_log_dir': opencode_config.get('conversation_log_dir', 'logs/opencode'),
        }
    
    def get_opencode_llm_config(self, provider: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Get LLM configuration for OpenCode containers.
        
        ONLY uses OpenCode-specific LLM configuration. Does NOT fall back to main LLM config.
        This ensures OpenCode uses separate API keys from the main application.
        
        IMPORTANT: For OpenCode, model is ALWAYS taken from environment variable (OPENCODE_*_MODEL),
        NOT from API request parameters. This ensures consistency and prevents accidental overrides.
        
        Args:
            provider: Optional provider override (from API request) - only used if OPENCODE_LLM_PROVIDER not set
            model: IGNORED for OpenCode - always uses OPENCODE_*_MODEL from environment
            
        Returns:
            LLM configuration dict for OpenCode
            
        Raises:
            ValueError: If OpenCode-specific API key is missing for the provider
        """
        # For OpenCode, always ignore model parameter from API - use environment variable only
        if model:
            logger.warning(
                f"[OpenCode Config] Model parameter '{model}' from API request is IGNORED for OpenCode. "
                f"OpenCode always uses OPENCODE_*_MODEL from environment variables for consistency."
            )
            model = None  # Ignore API override
        opencode_config = self.opencode
        opencode_llm_config = opencode_config.get('llm', {})
        
        # Debug: Log the full OpenCode LLM config (without exposing API keys)
        debug_config = {k: ('***' if 'key' in k.lower() or 'token' in k.lower() else v) for k, v in opencode_llm_config.items()}
        logger.info(f"[OpenCode Config] Full OpenCode LLM config: {debug_config}")
        
        # OpenCode MUST use OPENCODE_LLM_PROVIDER from environment - NO fallback, NO API override
        opencode_provider = opencode_llm_config.get('provider')
        if provider:
            logger.warning(
                f"[OpenCode Config] Provider parameter '{provider}' from API request is IGNORED for OpenCode. "
                f"OpenCode MUST use OPENCODE_LLM_PROVIDER from environment variables only."
            )
        
        if not opencode_provider or (isinstance(opencode_provider, str) and not opencode_provider.strip()):
            env_provider = os.getenv('OPENCODE_LLM_PROVIDER')
            logger.error(f"[OpenCode Config] OPENCODE_LLM_PROVIDER is not set or empty! Environment value: {repr(env_provider)}")
            raise ValueError(
                "OpenCode REQUIRES OPENCODE_LLM_PROVIDER to be set in your .env file. "
                "OpenCode does NOT use the main LLM provider configuration and does NOT accept API overrides. "
                f"Current environment value: {repr(env_provider)}"
            )
        
        provider = opencode_provider  # Use ONLY from environment, never from API parameter
        
        # Validate provider
        if not self.validate_llm_provider(provider):
            raise ValueError(f"Unsupported LLM provider: {provider}. Supported providers: {self.get_supported_providers()}")
        
        # Get max_tokens from OpenCode config only
        max_tokens_config = opencode_llm_config.get('max_tokens', '')
        max_tokens = None
        if max_tokens_config and (isinstance(max_tokens_config, str) and max_tokens_config.strip() or isinstance(max_tokens_config, int)):
            try:
                max_tokens = int(max_tokens_config)
            except (ValueError, TypeError):
                pass
        
        # Get temperature from OpenCode config only (no fallback to main LLM config)
        temperature = opencode_llm_config.get('temperature')
        if temperature is None or (isinstance(temperature, str) and not temperature.strip()):
            # Use default temperature if not specified in OpenCode config
            temperature = 0.7
        else:
            temperature = float(temperature)
        
        config = {
            'provider': provider,
            'system_prompt': self.llm.get('system_prompt', Prompts.get_default_system_prompt()),
            'temperature': temperature,
            'max_tokens': max_tokens
        }
        
        # Get API keys and models - ONLY from OpenCode-specific config, NO fallback
        if provider == 'openai':
            api_key_value = opencode_llm_config.get('openai_api_key')
            if not api_key_value or (isinstance(api_key_value, str) and not api_key_value.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_OPENAI_API_KEY to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['api_key'] = api_key_value
            config['openai_api_key'] = api_key_value
            # Only use OpenCode-specific model, no fallback to main LLM config
            # For OpenCode, model parameter is always ignored - use environment variable only
            default_model = opencode_llm_config.get('openai_model')
            if not default_model or (isinstance(default_model, str) and not default_model.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_OPENAI_MODEL to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['model'] = default_model  # Always use from environment, never from API parameter
        elif provider == 'claude':
            api_key_value = opencode_llm_config.get('anthropic_api_key')
            if not api_key_value or (isinstance(api_key_value, str) and not api_key_value.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_ANTHROPIC_API_KEY to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['api_key'] = api_key_value
            config['anthropic_api_key'] = api_key_value
            
            # Debug: Check environment variable directly
            env_model = os.getenv('OPENCODE_ANTHROPIC_MODEL')
            logger.info(f"[OpenCode Config] Environment variable OPENCODE_ANTHROPIC_MODEL: {repr(env_model)}")
            
            # Only use OpenCode-specific model, no fallback to main LLM config
            default_model = opencode_llm_config.get('anthropic_model')
            logger.info(f"[OpenCode Config] Raw config value from opencode.llm.anthropic_model: {repr(default_model)}")
            logger.info(f"[OpenCode Config] Type of default_model: {type(default_model).__name__}")
            
            # Check if it's empty string or None
            if not default_model or (isinstance(default_model, str) and not default_model.strip()):
                logger.error(f"[OpenCode Config] OPENCODE_ANTHROPIC_MODEL is not set or empty! Environment value: {repr(env_model)}")
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_ANTHROPIC_MODEL to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    f"Current environment value: {repr(env_model)}. "
                    "This environment variable MUST be set (e.g., OPENCODE_ANTHROPIC_MODEL=claude-haiku-4-5)."
                )
            
            # For OpenCode, model parameter is always ignored - use environment variable only
            final_model = default_model  # Always use from environment, never from API parameter
            config['model'] = final_model
            # Also set provider-specific key for compatibility
            config['anthropic_model'] = final_model
            logger.info(f"[OpenCode Config] Final Anthropic model configured: {final_model} (from OPENCODE_ANTHROPIC_MODEL env var, stored in both 'model' and 'anthropic_model' keys)")
        elif provider == 'gemini':
            api_key_value = opencode_llm_config.get('google_api_key')
            if not api_key_value or (isinstance(api_key_value, str) and not api_key_value.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_GOOGLE_API_KEY to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['api_key'] = api_key_value
            config['google_api_key'] = api_key_value
            # Only use OpenCode-specific model, no fallback to main LLM config
            # For OpenCode, model parameter is always ignored - use environment variable only
            default_model = opencode_llm_config.get('google_model')
            if not default_model or (isinstance(default_model, str) and not default_model.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_GOOGLE_MODEL to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['model'] = default_model  # Always use from environment, never from API parameter
        elif provider == 'kimi':
            api_key_value = opencode_llm_config.get('moonshot_api_key')
            if not api_key_value or (isinstance(api_key_value, str) and not api_key_value.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_MOONSHOT_API_KEY to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['api_key'] = api_key_value
            config['moonshot_api_key'] = api_key_value
            # Only use OpenCode-specific model, no fallback to main LLM config
            # For OpenCode, model parameter is always ignored - use environment variable only
            default_model = opencode_llm_config.get('moonshot_model')
            if not default_model or (isinstance(default_model, str) and not default_model.strip()):
                raise ValueError(
                    "OpenCode REQUIRES OPENCODE_MOONSHOT_MODEL to be set in your .env file. "
                    "NO fallback - OpenCode does NOT use the main LLM configuration. "
                    "This environment variable MUST be set."
                )
            config['model'] = default_model  # Always use from environment, never from API parameter
        
        # Validate model from environment (model parameter is ignored for OpenCode)
        if not self.validate_llm_model(provider, config['model']):
            raise ValueError(f"Unsupported model '{config['model']}' for provider '{provider}'. Supported models: {self.get_supported_models()[provider]}")
        
        return config
    
    def get_git_credentials(self) -> Dict[str, Optional[str]]:
        """Get git credentials for cloning repositories"""
        git_config = self.git
        return {
            'username': git_config.get('username') or os.getenv('GIT_USERNAME'),
            'password': git_config.get('password') or os.getenv('GIT_PASSWORD'),
        }
    
    def get_mcp_config(self) -> Dict[str, Any]:
        """Get MCP server configuration"""
        return self._config.get('mcp', {})
    
    def get_cors_origins(self) -> List[str]:
        """
        Get list of CORS allowed origins from configuration.
        
        Supports both 'allowed_origins' as comma-separated string or YAML list.
        Returns empty list if not configured (for fallback to defaults).
        """
        cors_config = self.cors
        
        # Try allowed_origins
        allowed_origins = cors_config.get('allowed_origins', '')
        if allowed_origins:
            # Handle comma-separated string
            if isinstance(allowed_origins, str):
                # Split by comma and strip whitespace
                origins_list = [o.strip() for o in allowed_origins.split(',') if o.strip()]
                if origins_list:
                    return origins_list
            # Handle list
            elif isinstance(allowed_origins, list):
                # Filter out empty strings
                origins_list = [o for o in allowed_origins if o and isinstance(o, str)]
                if origins_list:
                    return origins_list
        
        return []
    
    def get_supported_providers(self) -> List[str]:
        """Get list of supported LLM providers"""
        return ['openai', 'claude', 'gemini', 'kimi']
    
    def get_supported_models(self) -> Dict[str, List[str]]:
        """Get supported models for each provider"""
        return {
            'openai': [
                'o1', 'o3', 'o3-mini', 'o4-mini', 'gpt-5', 'gpt-5-mini', 'gpt-5-turbo', 'gpt-4.1', 'gpt-4.1-mini', 'gpt-4.1-nano', 'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4'
            ],
            'claude': [
                'claude-haiku-4-5', 'claude-sonnet-4-5', 'claude-opus-4-1-20250805', 'claude-opus-4-1', 'claude-opus-4-20250514', 'claude-opus-4-0', 
                'claude-sonnet-4-20250514', 'claude-sonnet-4-0', 'claude-3-7-sonnet-20250219', 'claude-3-7-sonnet-latest',
                'claude-3-5-sonnet-20241022', 'claude-3-5-sonnet-latest', 'claude-3-5-haiku-20241022', 'claude-3-5-haiku-latest'
                # Note: Date-suffixed variants (e.g., claude-haiku-4-5-20251001) are also supported via flexible validation
            ],
            'gemini': [
                'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite',
                'gemini-2.0-flash', 'gemini-2.0-flash-lite'
            ],
            'kimi': [
                'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k',
                'moonshot-v1-auto', 'kimi-latest',
                'kimi-k2-thinking', 'kimi-k2-thinking-turbo',
                'kimi-k2-turbo-preview', 'kimi-k2-0711-preview', 'kimi-k2-0905-preview',
                'kimi-thinking-preview',
                'moonshot-v1-8k-vision-preview', 'moonshot-v1-32k-vision-preview', 'moonshot-v1-128k-vision-preview'
            ]
        }
    
    def validate_llm_provider(self, provider: str) -> bool:
        """Validate if the provider is supported"""
        return provider in self.get_supported_providers()
    
    def validate_llm_model(self, provider: str, model: str) -> bool:
        """Validate if the model is supported for the given provider"""
        supported_models = self.get_supported_models()
        if provider not in supported_models:
            return False
        
        # Check exact match first
        if model in supported_models[provider]:
            return True
        
        # For Claude models, allow date-suffixed variants (e.g., claude-haiku-4-5-20251001)
        # This is needed for OpenCode which supports date-suffixed model names
        if provider == 'claude':
            import re
            # Remove date suffix (8 digits at the end: YYYYMMDD) to get base model
            # Examples: 
            #   - claude-haiku-4-5-20251001 -> claude-haiku-4-5
            #   - claude-sonnet-4-5-20250929 -> claude-sonnet-4-5
            #   - claude-3-5-haiku-20241022 -> claude-3-5-haiku (already in list)
            base_model = re.sub(r'-\d{8}$', '', model)
            # Check if base model (without date) is in supported list
            if base_model in supported_models[provider]:
                return True
        
        return False
    
    def get_llm_config(self, provider: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
        """Get configuration for the specified or default LLM provider"""
        # Use provided provider or default from config
        provider = provider or self.llm.get('provider', 'openai')
        
        # Validate provider
        if not self.validate_llm_provider(provider):
            raise ValueError(f"Unsupported LLM provider: {provider}. Supported providers: {self.get_supported_providers()}")
        
        # Get max_tokens from env/config, allowing empty string to mean "use defaults"
        # YAML may parse numbers as int, so handle both int and string
        max_tokens_config = self.llm.get('max_tokens', '')
        logger.info(f"Raw max_tokens from config: {repr(max_tokens_config)} (type: {type(max_tokens_config).__name__})")
        max_tokens = None
        
        # Handle None, empty string, or falsy values
        if max_tokens_config is None or (isinstance(max_tokens_config, str) and not max_tokens_config.strip()):
            logger.info("max_tokens not set in config or empty, using provider defaults")
        else:
            try:
                # Convert to int (handles both string "20000" and int 20000 from YAML)
                max_tokens = int(max_tokens_config)
                logger.info(f"Parsed max_tokens from config: {max_tokens}")
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid max_tokens config value: {max_tokens_config} (type: {type(max_tokens_config).__name__}), using provider defaults. Error: {e}")
        
        config = {
            'provider': provider,
            'system_prompt': self.llm.get('system_prompt', Prompts.get_default_system_prompt()),
            'temperature': float(self.llm.get('temperature', 0.7)),
            'max_tokens': max_tokens  # None means use provider defaults
        }
        
        if provider == 'openai':
            api_key_value = self.llm.get('openai_api_key')
            config['api_key'] = api_key_value
            config['openai_api_key'] = api_key_value  # Also set provider-specific key
            default_model = self.llm.get('openai_model') or self.llm.get('models', {}).get('openai', 'gpt-5-mini')
            config['model'] = model or default_model
        elif provider == 'claude':
            api_key_value = self.llm.get('anthropic_api_key')
            config['api_key'] = api_key_value
            config['anthropic_api_key'] = api_key_value  # Also set provider-specific key
            default_model = self.llm.get('anthropic_model') or self.llm.get('models', {}).get('claude', 'claude-sonnet-4-5')
            config['model'] = model or default_model
        elif provider == 'gemini':
            api_key_value = self.llm.get('google_api_key')
            config['api_key'] = api_key_value
            config['google_api_key'] = api_key_value  # Also set provider-specific key
            default_model = self.llm.get('google_model') or self.llm.get('models', {}).get('gemini', 'gemini-2.5-flash')
            config['model'] = model or default_model
        elif provider == 'kimi':
            api_key_value = self.llm.get('moonshot_api_key')
            config['api_key'] = api_key_value
            config['moonshot_api_key'] = api_key_value  # Also set provider-specific key
            default_model = self.llm.get('moonshot_model') or self.llm.get('models', {}).get('kimi', 'moonshot-v1-8k')
            config['model'] = model or default_model
        
        # Validate model if specified
        if model and not self.validate_llm_model(provider, config['model']):
            raise ValueError(f"Unsupported model '{config['model']}' for provider '{provider}'. Supported models: {self.get_supported_models()[provider]}")
        
        return config
    
    def validate(self) -> bool:
        """Validate that all required configuration is present"""
        errors = []
        
        # Check Jira config
        jira_required = ['server_url', 'username', 'api_token']
        for field in jira_required:
            if not self.jira.get(field):
                errors.append(f"Missing Jira configuration: {field}")
        
        # Check LLM config
        provider = self.llm.get('provider')
        if not provider:
            errors.append("Missing LLM provider configuration")
        else:
            try:
                llm_config = self.get_llm_config()
                if not llm_config.get('api_key'):
                    errors.append(f"Missing API key for LLM provider: {provider}")
            except ValueError as e:
                errors.append(f"LLM configuration error: {str(e)}")
        
        if errors:
            for error in errors:
                print(f"Configuration Error: {error}")
            return False
        
        return True
