"""
Template Store
Manages template storage for draft PR configurations
"""
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for template storage
TEMPLATE_BASE_DIR = Path("/tmp/augment/templates")


class TemplateStore:
    """
    Manages template storage for draft PR configurations.
    
    Templates are stored per-user in Redis or filesystem.
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize template store.
        
        Args:
            base_dir: Base directory for templates (default: /tmp/augment/templates)
        """
        self.base_dir = base_dir or TEMPLATE_BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_user_dir(self, user: str) -> Path:
        """Get directory for a specific user's templates"""
        # Sanitize username for filesystem
        safe_user = user.replace('/', '_').replace('\\', '_').replace('..', '_')
        return self.base_dir / safe_user
    
    def _get_template_path(self, user: str, template_id: str) -> Path:
        """Get file path for a template"""
        # Sanitize template_id to prevent path traversal
        safe_template_id = template_id.replace('/', '_').replace('\\', '_').replace('..', '_')
        # Remove any null bytes
        safe_template_id = safe_template_id.replace('\x00', '_')
        # Remove leading/trailing dots and spaces
        safe_template_id = safe_template_id.strip('. ')
        # Validate it's not empty
        if not safe_template_id:
            raise ValueError("Invalid template_id: empty after sanitization")
        
        user_dir = self._get_user_dir(user)
        return user_dir / f"{safe_template_id}.json"
    
    def create_template(
        self,
        user: str,
        name: str,
        repos: List[Dict[str, Any]],
        scope: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
        description: Optional[str] = None
    ) -> str:
        """
        Create a new template.
        
        Args:
            user: User identifier
            name: Template name
            repos: List of repositories
            scope: Optional scope constraints
            additional_context: Optional additional context
            description: Optional template description
            
        Returns:
            Template ID
        """
        import uuid
        template_id = str(uuid.uuid4())
        
        template_data = {
            "template_id": template_id,
            "name": name,
            "description": description,
            "repos": repos,
            "scope": scope,
            "additional_context": additional_context,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": user,
            "updated_at": None
        }
        
        user_dir = self._get_user_dir(user)
        user_dir.mkdir(parents=True, exist_ok=True)
        
        template_path = self._get_template_path(user, template_id)
        template_path.write_text(
            json.dumps(template_data, indent=2),
            encoding='utf-8'
        )
        
        logger.info(f"Created template {template_id} for user {user}")
        return template_id
    
    def get_template(self, user: str, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a template by ID.
        
        Args:
            user: User identifier
            template_id: Template ID
            
        Returns:
            Template data or None if not found
        """
        template_path = self._get_template_path(user, template_id)
        
        if not template_path.exists():
            return None
        
        try:
            data = json.loads(template_path.read_text(encoding='utf-8'))
            # Convert ISO strings back to datetime for response
            if "created_at" in data:
                data["created_at"] = datetime.fromisoformat(data["created_at"])
            if "updated_at" in data and data["updated_at"]:
                data["updated_at"] = datetime.fromisoformat(data["updated_at"])
            return data
        except Exception as e:
            logger.error(f"Failed to load template {template_id} for user {user}: {e}")
            return None
    
    def list_templates(self, user: str) -> List[Dict[str, Any]]:
        """
        List all templates for a user.
        
        Args:
            user: User identifier
            
        Returns:
            List of template summaries (without full data)
        """
        user_dir = self._get_user_dir(user)
        
        if not user_dir.exists():
            return []
        
        templates = []
        for template_file in user_dir.glob("*.json"):
            try:
                data = json.loads(template_file.read_text(encoding='utf-8'))
                # Return summary only
                templates.append({
                    "template_id": data.get("template_id"),
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "created_at": datetime.fromisoformat(data["created_at"]) if "created_at" in data else None,
                    "updated_at": datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
                })
            except Exception as e:
                logger.warning(f"Failed to load template from {template_file}: {e}")
                continue
        
        # Sort by created_at descending
        templates.sort(key=lambda x: x.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return templates
    
    def update_template(
        self,
        user: str,
        template_id: str,
        name: Optional[str] = None,
        repos: Optional[List[Dict[str, Any]]] = None,
        scope: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
        description: Optional[str] = None
    ) -> bool:
        """
        Update a template.
        
        Args:
            user: User identifier
            template_id: Template ID
            name: Optional new name
            repos: Optional new repos
            scope: Optional new scope
            additional_context: Optional new context
            description: Optional new description
            
        Returns:
            True if update succeeded
        """
        template = self.get_template(user, template_id)
        if not template:
            return False
        
        # Update fields
        if name is not None:
            template["name"] = name
        if repos is not None:
            template["repos"] = repos
        if scope is not None:
            template["scope"] = scope
        if additional_context is not None:
            template["additional_context"] = additional_context
        if description is not None:
            template["description"] = description
        
        template["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Save
        template_path = self._get_template_path(user, template_id)
        template_path.write_text(
            json.dumps(template, indent=2, default=str),
            encoding='utf-8'
        )
        
        logger.info(f"Updated template {template_id} for user {user}")
        return True
    
    def delete_template(self, user: str, template_id: str) -> bool:
        """
        Delete a template.
        
        Args:
            user: User identifier
            template_id: Template ID
            
        Returns:
            True if deletion succeeded
        """
        template_path = self._get_template_path(user, template_id)
        
        if not template_path.exists():
            return False
        
        try:
            template_path.unlink()
            logger.info(f"Deleted template {template_id} for user {user}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete template {template_id} for user {user}: {e}")
            return False


# Global template store instance
_template_store: Optional[TemplateStore] = None


def get_template_store() -> TemplateStore:
    """Get or create global template store instance"""
    global _template_store
    if _template_store is None:
        _template_store = TemplateStore()
    return _template_store
