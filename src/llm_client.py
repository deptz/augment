from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
import logging
import json

from .prompts import Prompts

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    def __init__(self, api_key: str, model: str, system_prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None):
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.config_max_tokens = max_tokens  # Global max_tokens from config (None = use provider defaults)
    
    @abstractmethod
    def generate_description(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """Generate description using the LLM provider"""
        pass
    
    def generate_json(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON response with enforced JSON mode (provider-specific implementation)
        
        Args:
            prompt: The prompt to send to the LLM (should include JSON format instructions)
            max_tokens: Maximum tokens to generate
            
        Returns:
            JSON string (guaranteed valid JSON, not wrapped in markdown)
        """
        # Default implementation: fallback to regular generation with JSON extraction
        # Subclasses should override this for provider-specific JSON enforcement
        response = self.generate_description(prompt)
        # Extract JSON from response if needed
        return self._extract_json_from_response(response)
    
    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON from response, handling markdown code blocks"""
        response = response.strip()
        
        # Remove markdown code blocks
        if response.startswith('```json'):
            response = response[7:]
        elif response.startswith('```'):
            response = response[3:]
        if response.endswith('```'):
            response = response[:-3]
        response = response.strip()
        
        # Prefer JSON objects over arrays (most use cases expect objects)
        # Try to find JSON object first
        object_start = response.find('{')
        array_start = response.find('[')
        
        # Use object if found, otherwise use array
        start_idx = object_start if object_start != -1 else array_start
        
        if start_idx != -1:
            # Find matching closing bracket/brace
            bracket_stack = []
            end_idx = start_idx
            for i in range(start_idx, len(response)):
                if response[i] in '[{':
                    bracket_stack.append(response[i])
                elif response[i] in ']}':
                    if bracket_stack:
                        bracket_stack.pop()
                        if not bracket_stack:
                            end_idx = i
                            break
            
            if end_idx > start_idx:
                return response[start_idx:end_idx + 1]
        
        return response
    
    def get_system_prompt(self) -> str:
        """Get the current system prompt"""
        return self.system_prompt
    
    def set_system_prompt(self, system_prompt: str) -> None:
        """Set a new system prompt (for temporary overrides)"""
        self.system_prompt = system_prompt
    
    def _build_prompt(self, ticket_info: str, prd_content: str = None, 
                     commits: List[str] = None, pull_requests: List[str] = None,
                     code_changes: dict = None) -> str:
        """Build the complete prompt for the LLM (DEPRECATED - use centralized templates)"""
        template = Prompts.get_legacy_build_prompt_template()
        
        # Build sections
        prd_content_section = f"\n**PRD/RFC Content:**\n{prd_content}" if prd_content else ""
        commits_section = f"\n**Related Commits:**\n" + "\n".join(commits) if commits else ""
        pull_requests_section = f"\n**Related Pull Requests:**\n" + "\n".join(pull_requests) if pull_requests else ""
        
        code_changes_section = ""
        if code_changes:
            changes_summary = []
            if code_changes.get('total_files'):
                changes_summary.append(f"Total files changed: {code_changes['total_files']}")
            if code_changes.get('additions'):
                changes_summary.append(f"Lines added: {code_changes['additions']}")
            if code_changes.get('deletions'):
                changes_summary.append(f"Lines deleted: {code_changes['deletions']}")
            if code_changes.get('file_types'):
                changes_summary.append(f"File types: {', '.join(code_changes['file_types'])}")
            
            if changes_summary:
                code_changes_section = f"\n**Code Changes Summary:**\n" + "\n".join(changes_summary)
        
        prompt = template.format(
            ticket_info=ticket_info,
            prd_content_section=prd_content_section,
            commits_section=commits_section,
            pull_requests_section=pull_requests_section,
            code_changes_section=code_changes_section
        )
        
        return prompt


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""
    
    def __init__(self, api_key: str, model: str, system_prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None):
        # GPT-5 variants only support temperature=1.0, override if needed
        if OpenAIProvider._is_gpt5_variant(model):
            if temperature != 1.0:
                logger.warning(f"GPT-5 variant '{model}' only supports temperature=1.0. Overriding temperature from {temperature} to 1.0")
            temperature = 1.0
        
        super().__init__(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("openai package is required for OpenAI provider")
    
    @staticmethod
    def _is_gpt5_variant(model: str) -> bool:
        """Check if model is a GPT-5 variant that requires temperature=1.0"""
        model_lower = model.lower()
        return any(gpt5_variant in model_lower for gpt5_variant in ['gpt-5', 'gpt5'])
    
    def _get_effective_temperature(self) -> float:
        """Get effective temperature (always 1.0 for GPT-5 variants)"""
        if OpenAIProvider._is_gpt5_variant(self.model):
            return 1.0
        return self.temperature
    
    def generate_description(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        try:
            # Log the prompts being sent to OpenAI
            logger.info("=" * 80)
            logger.info("🤖 OPENAI PROMPT DEBUG")
            logger.info("=" * 80)
            logger.info(f"📋 SYSTEM PROMPT:\n{self.system_prompt}")
            logger.info("-" * 80)
            logger.info(f"👤 USER PROMPT:\n{prompt}")
            logger.info("=" * 80)
            
            # Use config max_tokens if provided, otherwise use provider defaults
            # GPT-5 models need much higher limits because reasoning tokens count against completion tokens
            # Priority: per-call override > config max_tokens > GPT-5 override (16000) > default (2000)
            if max_tokens is not None:
                # Use per-call override
                max_completion_tokens = max_tokens
            elif self.config_max_tokens is not None:
                # Use config max_tokens, but ensure GPT-5 gets minimum 16000
                if OpenAIProvider._is_gpt5_variant(self.model) and self.config_max_tokens < 16000:
                    logger.warning(f"Config max_tokens={self.config_max_tokens} is insufficient for GPT-5. GPT-5 uses reasoning tokens (often 4000-8000+) before generating output. Overriding to 16000 tokens.")
                    max_completion_tokens = 16000
                else:
                    max_completion_tokens = self.config_max_tokens
            elif OpenAIProvider._is_gpt5_variant(self.model):
                max_completion_tokens = 16000  # High default for GPT-5 to account for reasoning tokens
                logger.info(f"Using high token limit ({max_completion_tokens}) for GPT-5 model to account for reasoning tokens")
            else:
                max_completion_tokens = 2000  # Default for other models
            
            # GPT-5 variants require temperature=1.0
            effective_temp = self._get_effective_temperature()
            if effective_temp != self.temperature:
                logger.info(f"Using effective temperature {effective_temp} for GPT-5 variant (configured: {self.temperature})")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=max_completion_tokens,
                temperature=effective_temp
            )
            
            result = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # Check if response was truncated or empty
            if finish_reason == 'length':
                logger.warning(f"⚠️ OpenAI response was truncated (finish_reason=length). Consider increasing max_tokens or reducing prompt size.")
                if not result:
                    logger.error("🚨 GPT-5 used all tokens for reasoning, no output generated.")
                    raise ValueError(f"GPT-5 exhausted all {max_completion_tokens} tokens on reasoning, leaving no room for output. Try reducing prompt complexity or increasing max_tokens.")
            
            logger.info(f"🤖 OPENAI RESPONSE LENGTH: {len(result) if result else 0} characters, finish_reason: {finish_reason}")
            
            # Debug: Print the full response details
            logger.info("-" * 80)
            logger.info("🔍 OPENAI FULL RESPONSE DEBUG:")
            logger.info(f"Response object: {response}")
            logger.info(f"Choices count: {len(response.choices) if response.choices else 0}")
            if response.choices:
                logger.info(f"First choice: {response.choices[0]}")
                logger.info(f"Message content: {response.choices[0].message.content}")
                logger.info(f"Finish reason: {response.choices[0].finish_reason}")
            logger.info(f"Usage: {response.usage}")
            logger.info("-" * 80)
            
            if result:
                logger.info(f"🤖 OPENAI RESPONSE PREVIEW:\n{result[:500]}...")
            else:
                logger.error("🚨 OPENAI RETURNED EMPTY RESPONSE!")
            
            return result
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
            raise
    
    def generate_json(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON response with OpenAI's JSON mode enforcement
        
        Note: OpenAI's JSON mode only supports JSON objects, not arrays.
        If the prompt requests an array, we'll wrap it in an object or use extraction.
        """
        try:
            # Check if prompt requests an array
            requests_array = "array" in prompt.lower() or "[\n" in prompt or '"[' in prompt
            
            # Ensure prompt requests JSON (OpenAI JSON mode requirement)
            json_prompt = prompt
            if "json" not in prompt.lower() and "```json" not in prompt.lower():
                json_instruction = Prompts.get_json_response_instruction()
                json_prompt = f"{prompt}\n\n{json_instruction}"
            
            # Use config max_tokens if provided, otherwise use provider defaults
            # GPT-5 models need much higher limits because reasoning tokens count against completion tokens
            # Priority: per-call override > config max_tokens > GPT-5 override (16000) > default (2000)
            if max_tokens is not None:
                # Use per-call override
                max_completion_tokens = max_tokens
            elif self.config_max_tokens is not None:
                # Use config max_tokens, but ensure GPT-5 gets minimum 16000
                if OpenAIProvider._is_gpt5_variant(self.model) and self.config_max_tokens < 16000:
                    logger.warning(f"Config max_tokens={self.config_max_tokens} is insufficient for GPT-5. GPT-5 uses reasoning tokens (often 4000-8000+) before generating output. Overriding to 16000 tokens.")
                    max_completion_tokens = 16000
                else:
                    max_completion_tokens = self.config_max_tokens
            elif OpenAIProvider._is_gpt5_variant(self.model):
                max_completion_tokens = 16000  # High default for GPT-5 to account for reasoning tokens
                logger.info(f"Using high token limit ({max_completion_tokens}) for GPT-5 model to account for reasoning tokens")
            else:
                max_completion_tokens = 2000  # Default for other models
            
            logger.info(f"Using OpenAI JSON mode for model: {self.model}")
            
            if requests_array:
                # OpenAI JSON mode requires objects, not arrays
                # For arrays, we'll use regular generation with extraction
                logger.info("Prompt requests array - using regular generation with JSON extraction")
                response_text = self.generate_description(json_prompt)
                return self._extract_json_from_response(response_text)
            
            # GPT-5 variants require temperature=1.0
            effective_temp = self._get_effective_temperature()
            
            # For objects, use strict JSON mode
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": json_prompt}
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=max_completion_tokens,
                temperature=effective_temp
            )
            
            result = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # Check if response was truncated or empty
            if finish_reason == 'length':
                logger.warning(f"⚠️ OpenAI JSON response was truncated (finish_reason=length). Consider increasing max_tokens or reducing prompt size.")
                if not result:
                    logger.error("🚨 GPT-5 used all tokens for reasoning, no JSON output generated.")
                    raise ValueError(f"GPT-5 exhausted all {max_completion_tokens} tokens on reasoning, leaving no room for JSON output. Try reducing prompt complexity or increasing max_tokens.")
            
            logger.info(f"OpenAI JSON response length: {len(result) if result else 0} characters, finish_reason: {finish_reason}")
            
            # Validate JSON
            try:
                json.loads(result)
                logger.info("✅ OpenAI returned valid JSON")
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ OpenAI JSON mode returned invalid JSON: {e}")
                # Fallback to extraction
                result = self._extract_json_from_response(result)
            
            return result
        except Exception as e:
            logger.error(f"OpenAI JSON generation error: {e}")
            # Fallback to regular generation
            logger.warning("Falling back to regular generation mode")
            return self._extract_json_from_response(self.generate_description(prompt))


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider"""
    
    def __init__(self, api_key: str, model: str, system_prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None):
        super().__init__(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        # Default max_tokens for Claude (8000) unless overridden by config
        self.default_max_tokens = self.config_max_tokens if self.config_max_tokens is not None else 8000
        logger.info(f"ClaudeProvider initialized: config_max_tokens={self.config_max_tokens}, default_max_tokens={self.default_max_tokens}")
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package is required for Claude provider")
    
    def generate_description(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        try:
            # Use provided max_tokens, config max_tokens, or default
            tokens_to_use = max_tokens if max_tokens is not None else self.default_max_tokens
            
            logger.info(f"Calling Claude with max_tokens={tokens_to_use}")
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=tokens_to_use,
                temperature=self.temperature,
                system=self.system_prompt,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Check if response was truncated
            stop_reason = response.stop_reason
            if stop_reason == "max_tokens":
                logger.warning(f"Claude response was truncated due to max_tokens limit ({tokens_to_use})")
            
            result = response.content[0].text
            logger.info(f"Claude response length: {len(result)} characters, stop_reason: {stop_reason}")
            
            return result
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise
    
    def generate_json(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON response with Claude using prompt-based JSON generation
        
        Claude does not support response_format parameter (that's OpenAI-specific).
        Instead, we use prompt-based JSON generation with extraction, which works reliably
        across all Claude models.
        """
        try:
            # Use provided max_tokens, config max_tokens, or default
            tokens_to_use = max_tokens if max_tokens is not None else self.default_max_tokens
            
            logger.info(f"Using Claude JSON mode for model: {self.model}")
            
            # Ensure prompt requests JSON format
            # For Claude, always add explicit JSON instructions (more forceful for prompt-based generation)
            # Claude doesn't have structured output enforcement, so explicit instructions are critical
            json_instruction = Prompts.get_claude_json_response_instruction()
            json_prompt = f"{prompt}\n\n{json_instruction}"
            
            # Claude uses prompt-based JSON generation with extraction
            logger.info("Using Claude regular generation with JSON extraction")
            response_text = self.generate_description(json_prompt, max_tokens=tokens_to_use)
            
            # Extract JSON from response (prefers objects over arrays)
            extracted_json = self._extract_json_from_response(response_text)
            
            # Log what we extracted for debugging
            if extracted_json != response_text:
                logger.info(f"Extracted JSON fragment from response (length: {len(extracted_json)} chars, original: {len(response_text)} chars)")
                logger.debug(f"Extracted JSON preview: {extracted_json[:200]}...")
            else:
                logger.info(f"Using full response as JSON (length: {len(extracted_json)} chars)")
                logger.debug(f"Full JSON preview: {extracted_json[:200]}...")
            
            result = extracted_json
                    
            # Validate JSON
            try:
                parsed = json.loads(result)
                logger.info(f"✅ Claude returned valid JSON (type: {type(parsed).__name__})")
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Claude JSON extraction returned invalid JSON: {e}")
                logger.warning(f"Response preview: {result[:500]}")
                raise ValueError(f"Failed to extract valid JSON from Claude response: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Claude JSON generation error: {e}")
            # Re-raise to let caller handle
            raise


class GeminiProvider(LLMProvider):
    """Google Gemini provider"""
    
    def __init__(self, api_key: str, model: str, system_prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None):
        super().__init__(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        # Default max_output_tokens for Gemini (8192) unless overridden by config
        self.default_max_output_tokens = self.config_max_tokens if self.config_max_tokens is not None else 8192
        logger.info(f"GeminiProvider initialized: config_max_tokens={self.config_max_tokens}, default_max_output_tokens={self.default_max_output_tokens}")
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            # Configure generation settings with temperature and max_output_tokens
            self.generation_config = genai.types.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.default_max_output_tokens
            )
            self.client = genai.GenerativeModel(model, generation_config=self.generation_config)
            logger.info(f"DEBUG: Successfully initialized Gemini model: {model}")
        except ImportError:
            raise ImportError("google-generativeai package is required for Gemini provider")
    
    def generate_description(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        try:
            # Combine system prompt with user prompt for Gemini
            full_prompt = f"{self.system_prompt}\n\n{prompt}"
            # Use provided max_tokens, config max_tokens, or default
            tokens_to_use = max_tokens if max_tokens is not None else self.default_max_output_tokens
            
            logger.info(f"Calling Gemini with max_output_tokens={tokens_to_use}")
            
            # Create generation config with max_output_tokens for this call
            import google.generativeai as genai
            generation_config = genai.types.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=tokens_to_use
            )
            
            response = self.client.generate_content(full_prompt, generation_config=generation_config)
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise
    
    def generate_json(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON response with Gemini's JSON mode enforcement
        
        Gemini supports response_mime_type="application/json" for strict JSON output.
        """
        try:
            import google.generativeai as genai
            
            logger.info(f"Using Gemini JSON mode for model: {self.model}")
            
            # Combine system prompt with user prompt
            json_instruction = Prompts.get_json_response_instruction()
            full_prompt = f"{self.system_prompt}\n\n{prompt}\n\n{json_instruction}"
            
            # Use provided max_tokens, config max_tokens, or default
            tokens_to_use = max_tokens if max_tokens is not None else self.default_max_output_tokens
            
            logger.info(f"GeminiProvider.generate_json: max_tokens param={max_tokens}, default_max_output_tokens={self.default_max_output_tokens}, using tokens_to_use={tokens_to_use}")
            logger.info(f"Calling Gemini JSON mode with max_output_tokens={tokens_to_use}")
            
            # Configure generation with JSON response type and max_output_tokens
            json_generation_config = genai.types.GenerationConfig(
                temperature=self.temperature,
                response_mime_type="application/json",
                max_output_tokens=tokens_to_use
            )
            
            # Create model with JSON config
            json_model = genai.GenerativeModel(self.model, generation_config=json_generation_config)
            
            response = json_model.generate_content(full_prompt)
            result = response.text
            
            logger.info(f"Gemini JSON response length: {len(result) if result else 0} characters")
            
            # Validate JSON
            try:
                json.loads(result)
                logger.info("✅ Gemini returned valid JSON")
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Gemini JSON mode returned invalid JSON: {e}")
                # Fallback to extraction
                result = self._extract_json_from_response(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Gemini JSON generation error: {e}")
            # Fallback to regular generation
            logger.warning("Falling back to regular generation mode")
            return self._extract_json_from_response(self.generate_description(prompt))


class KimiProvider(LLMProvider):
    """Moonshot AI KIMI provider (OpenAI-compatible API)"""
    
    def __init__(self, api_key: str, model: str, system_prompt: str, temperature: float = 0.7, max_tokens: Optional[int] = None):
        super().__init__(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        try:
            from openai import OpenAI
            # KIMI uses OpenAI-compatible API with custom base URL
            self.client = OpenAI(api_key=api_key, base_url="https://api.moonshot.ai/v1")
        except ImportError:
            raise ImportError("openai package is required for KIMI provider")
    
    def generate_description(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        try:
            # Log the prompts being sent to KIMI
            logger.info("=" * 80)
            logger.info("🤖 KIMI PROMPT DEBUG")
            logger.info("=" * 80)
            logger.info(f"📋 SYSTEM PROMPT:\n{self.system_prompt}")
            logger.info("-" * 80)
            logger.info(f"👤 USER PROMPT:\n{prompt}")
            logger.info("=" * 80)
            
            # Use config max_tokens if provided, otherwise use default (2000)
            # Priority: per-call override > config max_tokens > default (2000)
            if max_tokens is not None:
                max_completion_tokens = max_tokens
            elif self.config_max_tokens is not None:
                max_completion_tokens = self.config_max_tokens
            else:
                max_completion_tokens = 2000  # Default for KIMI
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_completion_tokens=max_completion_tokens,
                temperature=self.temperature
            )
            
            result = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # Check if response was truncated or empty
            if finish_reason == 'length':
                logger.warning(f"⚠️ KIMI response was truncated (finish_reason=length). Consider increasing max_tokens or reducing prompt size.")
                if not result:
                    logger.error("🚨 KIMI used all tokens, no output generated.")
                    raise ValueError(f"KIMI exhausted all {max_completion_tokens} tokens. Try reducing prompt complexity or increasing max_tokens.")
            
            logger.info(f"🤖 KIMI RESPONSE LENGTH: {len(result) if result else 0} characters, finish_reason: {finish_reason}")
            
            # Debug: Print the full response details
            logger.info("-" * 80)
            logger.info("🔍 KIMI FULL RESPONSE DEBUG:")
            logger.info(f"Response object: {response}")
            logger.info(f"Choices count: {len(response.choices) if response.choices else 0}")
            if response.choices:
                logger.info(f"First choice: {response.choices[0]}")
                logger.info(f"Message content: {response.choices[0].message.content}")
                logger.info(f"Finish reason: {response.choices[0].finish_reason}")
            logger.info(f"Usage: {response.usage}")
            logger.info("-" * 80)
            
            if result:
                logger.info(f"🤖 KIMI RESPONSE PREVIEW:\n{result[:500]}...")
            else:
                logger.error("🚨 KIMI RETURNED EMPTY RESPONSE!")
            
            return result
        except Exception as e:
            # Import OpenAI exception to catch it specifically
            try:
                from openai import NotFoundError, PermissionDeniedError, AuthenticationError
            except ImportError:
                NotFoundError = PermissionDeniedError = AuthenticationError = None
            
            error_str = str(e)
            
            # Clarify that this is a KIMI API error (not OpenAI), even though we use OpenAI client library
            if NotFoundError and isinstance(e, NotFoundError):
                logger.error(f"🚨 KIMI API Error (404 Not Found): Model '{self.model}' not found or not available")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                logger.error(f"💡 Try using one of these available KIMI models: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo")
                # Re-raise with clearer message
                raise ValueError(f"KIMI model '{self.model}' not found or not available. Try: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, or kimi-k2-thinking-turbo") from e
            elif PermissionDeniedError and isinstance(e, PermissionDeniedError):
                logger.error(f"🚨 KIMI API Error (Permission Denied): Your API key may not have access to model '{self.model}'")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                logger.error(f"💡 Check your MOONSHOT_API_KEY permissions or try a different model")
                raise ValueError(f"KIMI API permission denied for model '{self.model}'. Check API key permissions or try a different model.") from e
            elif AuthenticationError and isinstance(e, AuthenticationError):
                logger.error(f"🚨 KIMI API Error (Authentication Failed): Invalid API key")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                raise ValueError(f"KIMI API authentication failed. Check your MOONSHOT_API_KEY.") from e
            else:
                logger.error(f"KIMI API error (using OpenAI-compatible client): {e}")
                # Provide helpful error message for model not found errors
                if "404" in error_str or "Not found the model" in error_str or "Permission denied" in error_str:
                    logger.error(f"⚠️ Model '{self.model}' may not be available or your API key may not have access to it.")
                    logger.error(f"💡 Try using one of these models: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo")
            raise
    
    def generate_json(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON response with KIMI's JSON mode enforcement (OpenAI-compatible)
        
        Note: KIMI's JSON mode only supports JSON objects, not arrays.
        If the prompt requests an array, we'll wrap it in an object or use extraction.
        """
        try:
            # Check if prompt requests an array
            requests_array = "array" in prompt.lower() or "[\n" in prompt or '"[' in prompt
            
            # Ensure prompt requests JSON (KIMI JSON mode requirement)
            json_prompt = prompt
            if "json" not in prompt.lower() and "```json" not in prompt.lower():
                json_instruction = Prompts.get_json_response_instruction()
                json_prompt = f"{prompt}\n\n{json_instruction}"
            
            # Use config max_tokens if provided, otherwise use default (2000)
            # Priority: per-call override > config max_tokens > default (2000)
            if max_tokens is not None:
                max_completion_tokens = max_tokens
            elif self.config_max_tokens is not None:
                max_completion_tokens = self.config_max_tokens
            else:
                max_completion_tokens = 2000  # Default for KIMI
            
            logger.info(f"Using KIMI JSON mode for model: {self.model}")
            
            if requests_array:
                # KIMI JSON mode requires objects, not arrays
                # For arrays, we'll use regular generation with extraction
                logger.info("Prompt requests array - using regular generation with JSON extraction")
                response_text = self.generate_description(json_prompt)
                return self._extract_json_from_response(response_text)
            
            # For objects, use strict JSON mode
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": json_prompt}
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=max_completion_tokens,
                temperature=self.temperature
            )
            
            result = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # Check if response was truncated or empty
            if finish_reason == 'length':
                logger.warning(f"⚠️ KIMI JSON response was truncated (finish_reason=length). Consider increasing max_tokens or reducing prompt size.")
                if not result:
                    logger.error("🚨 KIMI used all tokens for reasoning, no JSON output generated.")
                    raise ValueError(f"KIMI exhausted all {max_completion_tokens} tokens, leaving no room for JSON output. Try reducing prompt complexity or increasing max_tokens.")
            
            logger.info(f"KIMI JSON response length: {len(result) if result else 0} characters, finish_reason: {finish_reason}")
            
            # Validate JSON
            try:
                json.loads(result)
                logger.info("✅ KIMI returned valid JSON")
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ KIMI JSON mode returned invalid JSON: {e}")
                # Fallback to extraction
                result = self._extract_json_from_response(result)
            
            return result
        except Exception as e:
            # Import OpenAI exception to catch it specifically
            try:
                from openai import NotFoundError, PermissionDeniedError, AuthenticationError
            except ImportError:
                NotFoundError = PermissionDeniedError = AuthenticationError = None
            
            error_str = str(e)
            
            # Clarify that this is a KIMI API error (not OpenAI), even though we use OpenAI client library
            if NotFoundError and isinstance(e, NotFoundError):
                logger.error(f"🚨 KIMI API Error (404 Not Found): Model '{self.model}' not found or not available")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                logger.error(f"💡 Try using one of these available KIMI models: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo")
                # Re-raise with clearer message
                raise ValueError(f"KIMI model '{self.model}' not found or not available. Try: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, or kimi-k2-thinking-turbo") from e
            elif PermissionDeniedError and isinstance(e, PermissionDeniedError):
                logger.error(f"🚨 KIMI API Error (Permission Denied): Your API key may not have access to model '{self.model}'")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                logger.error(f"💡 Check your MOONSHOT_API_KEY permissions or try a different model")
                raise ValueError(f"KIMI API permission denied for model '{self.model}'. Check API key permissions or try a different model.") from e
            elif AuthenticationError and isinstance(e, AuthenticationError):
                logger.error(f"🚨 KIMI API Error (Authentication Failed): Invalid API key")
                logger.error(f"⚠️ This error comes from KIMI's API (we use OpenAI-compatible client), not OpenAI")
                raise ValueError(f"KIMI API authentication failed. Check your MOONSHOT_API_KEY.") from e
            else:
                logger.error(f"KIMI JSON generation error (using OpenAI-compatible client): {e}")
                # Provide helpful error message for model not found errors
                if "404" in error_str or "Not found the model" in error_str or "Permission denied" in error_str:
                    logger.error(f"⚠️ Model '{self.model}' may not be available or your API key may not have access to it.")
                    logger.error(f"💡 Try using one of these models: moonshot-v1-8k, moonshot-v1-32k, moonshot-v1-128k, kimi-latest, kimi-k2-thinking, kimi-k2-thinking-turbo")
            # Fallback to regular generation
            logger.warning("Falling back to regular generation mode")
            return self._extract_json_from_response(self.generate_description(prompt))


class LLMClient:
    """Factory class for LLM providers"""
    
    def __init__(self, config: dict):
        self.provider_name = config['provider'].lower()
        self.config = config
        self.default_max_tokens = config.get('max_tokens')  # Global max_tokens from config (None = use provider defaults)
        logger.info(f"LLMClient initialized: provider={self.provider_name}, config_max_tokens={self.default_max_tokens}")
        logger.info(f"LLMClient.__init__: config.get('max_tokens') returned: {repr(config.get('max_tokens'))}, type: {type(config.get('max_tokens'))}")
        self.provider = self._create_provider(config)
    
    def _create_provider(self, config: dict) -> LLMProvider:
        """Create the appropriate LLM provider"""
        provider = config['provider'].lower()
        api_key = config['api_key']
        model = config['model']
        system_prompt = config['system_prompt']
        temperature = config.get('temperature', 0.7)
        max_tokens = config.get('max_tokens')  # Pass max_tokens to providers
        
        if provider == "openai":
            return OpenAIProvider(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        elif provider == "claude":
            return ClaudeProvider(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        elif provider == "gemini":
            return GeminiProvider(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        elif provider == "kimi":
            return KimiProvider(api_key, model, system_prompt, temperature, max_tokens=max_tokens)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
    
    def get_system_prompt(self) -> str:
        """Get the current system prompt from the provider"""
        return self.provider.get_system_prompt()
    
    def set_system_prompt(self, system_prompt: str) -> None:
        """Set a new system prompt on the provider (for temporary overrides)"""
        self.provider.set_system_prompt(system_prompt)
    
    def generate_description(self, ticket_info: str, prd_content: str = None, 
                           commits: List[str] = None, pull_requests: List[str] = None,
                           code_changes: dict = None) -> str:
        """Generate description using the configured provider"""
        prompt = self.provider._build_prompt(ticket_info, prd_content, commits, pull_requests, code_changes)
        # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
        return self.provider.generate_description(prompt, max_tokens=None)
    
    def generate_content(self, prompt: str, system_prompt: str = None, max_tokens: Optional[int] = None) -> str:
        """
        Generate content using the configured provider with custom prompts
        
        Args:
            prompt: The prompt to send to the LLM
            system_prompt: Optional system prompt override
            max_tokens: Maximum tokens to generate (default: config max_tokens or provider default)
            
        Returns:
            Generated content as string
        """
        # Use config max_tokens as default if not provided
        if max_tokens is None:
            max_tokens = self.default_max_tokens
        
        # Temporarily override system prompt if provided
        original_prompt = None
        if system_prompt:
            original_prompt = self.provider.get_system_prompt()
            self.provider.set_system_prompt(system_prompt)
        
        try:
            # Call provider's generate_description with max_tokens (all providers support it now)
            result = self.provider.generate_description(prompt, max_tokens=max_tokens)
            return result
        finally:
            # Restore original system prompt if it was overridden
            if original_prompt:
                self.provider.set_system_prompt(original_prompt)
    
    def generate_content_json(self, prompt: str, system_prompt: str = None, max_tokens: Optional[int] = None) -> str:
        """
        Generate JSON content with enforced JSON mode (unified across all providers)
        
        This method uses provider-specific JSON enforcement:
        - OpenAI: response_format={"type": "json_object"}
        - Claude: Prompt-based JSON generation with extraction (Claude doesn't support response_format)
        - Gemini: response_mime_type="application/json"
        - KIMI: response_format={"type": "json_object"} (OpenAI-compatible)
        
        Args:
            prompt: The prompt to send to the LLM (should include JSON format instructions)
            system_prompt: Optional system prompt override
            max_tokens: Maximum tokens to generate (default: config max_tokens or provider default)
            
        Returns:
            JSON string (guaranteed valid JSON, not wrapped in markdown)
        """
        # Use config max_tokens as default if not provided
        if max_tokens is None:
            max_tokens = self.default_max_tokens
            logger.info(f"generate_content_json: Using default_max_tokens={max_tokens} from config")
        else:
            logger.info(f"generate_content_json: Using provided max_tokens={max_tokens}")
        
        # Temporarily override system prompt if provided
        original_prompt = None
        if system_prompt:
            original_prompt = self.provider.get_system_prompt()
            self.provider.set_system_prompt(system_prompt)
        
        try:
            # Call provider's generate_json method (pass max_tokens, provider will use config default if None)
            logger.info(f"generate_content_json: Calling provider.generate_json with max_tokens={max_tokens}")
            result = self.provider.generate_json(prompt, max_tokens=max_tokens)
            
            # Final validation - ensure it's valid JSON
            try:
                json.loads(result)
                logger.info("✅ Final JSON validation passed")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Generated response is not valid JSON: {e}")
                logger.error(f"Response preview: {result[:500]}")
                raise ValueError(f"LLM did not return valid JSON: {e}")
            
            return result
        finally:
            # Restore original system prompt if it was overridden
            if original_prompt:
                self.provider.set_system_prompt(original_prompt)
    
    def test_connection(self) -> bool:
        """Test if the LLM provider is working"""
        try:
            test_prompt = "Hello, please respond with 'Connection successful'"
            # max_tokens=None uses config default (from LLM_MAX_TOKENS env var)
            response = self.provider.generate_description(test_prompt, max_tokens=None)
            return "successful" in response.lower()
        except Exception as e:
            logger.error(f"LLM connection test failed: {e}")
            return False
