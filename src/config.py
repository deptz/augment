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
        load_dotenv()
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
        return provider in supported_models and model in supported_models[provider]
    
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
            config['api_key'] = self.llm.get('openai_api_key')
            default_model = self.llm.get('openai_model') or self.llm.get('models', {}).get('openai', 'gpt-5-mini')
            config['model'] = model or default_model
        elif provider == 'claude':
            config['api_key'] = self.llm.get('anthropic_api_key')
            default_model = self.llm.get('anthropic_model') or self.llm.get('models', {}).get('claude', 'claude-sonnet-4-5')
            config['model'] = model or default_model
        elif provider == 'gemini':
            config['api_key'] = self.llm.get('google_api_key')
            default_model = self.llm.get('google_model') or self.llm.get('models', {}).get('gemini', 'gemini-2.5-flash')
            config['model'] = model or default_model
        elif provider == 'kimi':
            config['api_key'] = self.llm.get('moonshot_api_key')
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
