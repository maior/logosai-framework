"""
Template Renderer for LogosAI

Handles rendering of templates with context and post-processing.
"""

import sys
from typing import Dict, Any, Optional
from datetime import datetime
import logging

try:
    import black
    HAS_BLACK = True
except ImportError:
    HAS_BLACK = False
    
from .loader import TemplateLoader

logger = logging.getLogger(__name__)


class TemplateRenderer:
    """Renders templates with context and applies post-processing"""
    
    def __init__(self, loader: TemplateLoader):
        """
        Initialize the renderer.
        
        Args:
            loader: Template loader instance
        """
        self.loader = loader
        
    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        """
        Render a template with the given context.
        
        Args:
            template_name: Name of the template to render
            context: Context dictionary for template rendering
            
        Returns:
            Rendered template string
        """
        # Load template
        template = self.loader.load_template(template_name)
        
        # Add default context
        default_context = self._get_default_context()
        full_context = {**default_context, **context}
        
        # Render template
        rendered = template.render(full_context)
        
        # Post-process if it's a Python file
        if template_name.endswith('.py.jinja2'):
            rendered = self._format_python_code(rendered)
            
        return rendered
        
    def _get_default_context(self) -> Dict[str, Any]:
        """Get default context values"""
        return {
            'timestamp': datetime.now().isoformat(),
            'logosai_version': self._get_logosai_version(),
            'python_version': sys.version.split()[0],
            'generator': 'LogosAI Template Engine'
        }
        
    def _get_logosai_version(self) -> str:
        """Get LogosAI version"""
        try:
            from logosai import __version__
            return __version__
        except ImportError:
            return "1.0.0"
            
    def _format_python_code(self, code: str) -> str:
        """
        Format Python code using black if available.
        
        Args:
            code: Python code string
            
        Returns:
            Formatted code string
        """
        if not HAS_BLACK:
            logger.debug("Black not available, skipping code formatting")
            return code
            
        try:
            formatted = black.format_str(code, mode=black.Mode(
                target_versions={black.TargetVersion.PY38},
                line_length=88,
                string_normalization=True,
                is_pyi=False,
            ))
            return formatted
        except Exception as e:
            logger.warning(f"Failed to format code with black: {e}")
            return code
            
    def render_string(self, template_string: str, context: Dict[str, Any]) -> str:
        """
        Render a template from a string.
        
        Args:
            template_string: Template content as string
            context: Context dictionary
            
        Returns:
            Rendered string
        """
        template = self.loader.env.from_string(template_string)
        full_context = {**self._get_default_context(), **context}
        return template.render(full_context)
        
    def batch_render(self, templates: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
        """
        Render multiple templates in batch.
        
        Args:
            templates: Dictionary mapping template names to their contexts
            
        Returns:
            Dictionary mapping template names to rendered content
        """
        results = {}
        
        for template_name, context in templates.items():
            try:
                results[template_name] = self.render(template_name, context)
            except Exception as e:
                logger.error(f"Failed to render {template_name}: {e}")
                results[template_name] = None
                
        return results