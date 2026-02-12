"""
Template Engine for LogosAI

Main interface for template operations.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import logging

from .loader import TemplateLoader
from .renderer import TemplateRenderer
from .validator import TemplateValidator, ValidationError
from .registry import TemplateRegistry, TemplateMetadata

logger = logging.getLogger(__name__)


class TemplateEngine:
    """Main template engine interface"""
    
    def __init__(self, 
                 template_dirs: Optional[List[Path]] = None,
                 metadata_file: Optional[Path] = None):
        """
        Initialize the template engine.
        
        Args:
            template_dirs: Optional list of template directories
            metadata_file: Optional path to metadata file
        """
        self.loader = TemplateLoader(template_dirs)
        self.renderer = TemplateRenderer(self.loader)
        self.validator = TemplateValidator()
        self.registry = TemplateRegistry(metadata_file)
        
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Render a template with context.
        
        Args:
            template_name: Name of the template
            context: Context dictionary
            
        Returns:
            Rendered code string
        """
        # Get metadata to check required params
        metadata = self.registry.get(template_name)
        if metadata:
            missing_params = set(metadata.required_params) - set(context.keys())
            if missing_params:
                logger.warning(f"Missing required parameters for {template_name}: {missing_params}")
                
        # Render template
        rendered = self.renderer.render(template_name, context)
        return rendered
        
    def validate(self, code: str) -> Tuple[bool, List[ValidationError]]:
        """
        Validate rendered code.
        
        Args:
            code: Python code to validate
            
        Returns:
            Tuple of (is_valid, errors)
        """
        return self.validator.validate_rendered_code(code)
        
    def render_and_validate(self, template_name: str, 
                          context: Dict[str, Any]) -> Tuple[str, bool, List[ValidationError]]:
        """
        Render a template and validate the result.
        
        Args:
            template_name: Name of the template
            context: Context dictionary
            
        Returns:
            Tuple of (rendered_code, is_valid, errors)
        """
        rendered = self.render(template_name, context)
        is_valid, errors = self.validate(rendered)
        return rendered, is_valid, errors
        
    def list_templates(self, category: Optional[str] = None) -> List[str]:
        """
        List available templates.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of template names
        """
        return self.loader.list_templates(category)
        
    def search(self, query: Optional[str] = None,
               category: Optional[str] = None,
               tags: Optional[List[str]] = None) -> List[TemplateMetadata]:
        """
        Search for templates.
        
        Args:
            query: Text search query
            category: Category filter
            tags: Tag filter
            
        Returns:
            List of matching template metadata
        """
        return self.registry.search(query, category, tags)
        
    def get_metadata(self, template_name: str) -> Optional[TemplateMetadata]:
        """Get metadata for a template"""
        return self.registry.get(template_name)
        
    def get_example_usage(self, template_name: str) -> Optional[str]:
        """Get example usage for a template"""
        metadata = self.registry.get(template_name)
        return metadata.example_usage if metadata else None
        
    def batch_render(self, requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Render multiple templates in batch.
        
        Args:
            requests: List of dicts with 'template' and 'context' keys
            
        Returns:
            List of results with 'template', 'code', 'valid', and 'errors' keys
        """
        results = []
        
        for request in requests:
            template_name = request['template']
            context = request['context']
            
            try:
                code, is_valid, errors = self.render_and_validate(template_name, context)
                results.append({
                    'template': template_name,
                    'code': code,
                    'valid': is_valid,
                    'errors': [str(e) for e in errors]
                })
            except Exception as e:
                results.append({
                    'template': template_name,
                    'code': None,
                    'valid': False,
                    'errors': [str(e)]
                })
                
        return results
        
    def register_template(self, metadata: TemplateMetadata):
        """Register a new template"""
        self.registry.register(metadata)
        
    def reload_templates(self):
        """Reload all templates and clear caches"""
        self.loader.reload_templates()
        logger.info("Templates reloaded")
        
    def add_template_directory(self, directory: Path):
        """Add a new template directory"""
        self.loader.add_template_dir(directory)
        logger.info(f"Added template directory: {directory}")
        
    def get_categories(self) -> List[str]:
        """Get all available template categories"""
        return self.registry.get_categories()
        
    def get_tags(self) -> List[str]:
        """Get all available template tags"""
        return self.registry.get_all_tags()