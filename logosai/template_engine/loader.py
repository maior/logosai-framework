"""
Template Loader for LogosAI

Handles loading and caching of Jinja2 templates.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional
from jinja2 import Environment, FileSystemLoader, Template, TemplateNotFound
import logging

logger = logging.getLogger(__name__)


class TemplateLoader:
    """Loads and manages Jinja2 templates for agent generation"""
    
    def __init__(self, template_dirs: Optional[List[Path]] = None):
        """
        Initialize the template loader.
        
        Args:
            template_dirs: List of directories to search for templates.
                         If None, uses default LogosAI template directories.
        """
        self.template_dirs = template_dirs or self._get_default_dirs()
        self.env = self._create_jinja_env()
        self._cache: Dict[str, Template] = {}
        
    def _get_default_dirs(self) -> List[Path]:
        """Get default template directories"""
        base_dir = Path(__file__).parent.parent / "templates"
        return [base_dir]
        
    def _create_jinja_env(self) -> Environment:
        """Create and configure Jinja2 environment"""
        return Environment(
            loader=FileSystemLoader(self.template_dirs),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            line_statement_prefix='#',
            line_comment_prefix='##',
            extensions=['jinja2.ext.do', 'jinja2.ext.loopcontrols']
        )
        
    def load_template(self, template_name: str) -> Template:
        """
        Load a template by name.
        
        Args:
            template_name: Name of the template file (e.g., 'base/basic_agent.py.jinja2')
            
        Returns:
            Loaded Jinja2 template
            
        Raises:
            TemplateNotFound: If template doesn't exist
        """
        if template_name not in self._cache:
            try:
                template = self.env.get_template(template_name)
                self._cache[template_name] = template
                logger.debug(f"Loaded template: {template_name}")
            except TemplateNotFound:
                logger.error(f"Template not found: {template_name}")
                raise
                
        return self._cache[template_name]
        
    def list_templates(self, category: Optional[str] = None) -> List[str]:
        """
        List available templates.
        
        Args:
            category: Optional category filter (e.g., 'base', 'patterns')
            
        Returns:
            List of template names
        """
        templates = []
        
        for template_dir in self.template_dirs:
            search_dir = template_dir / category if category else template_dir
            
            if search_dir.exists():
                for root, _, files in os.walk(search_dir):
                    root_path = Path(root)
                    for file in files:
                        if file.endswith('.jinja2'):
                            # Get relative path from template_dir
                            rel_path = (root_path / file).relative_to(template_dir)
                            templates.append(str(rel_path))
                            
        return sorted(templates)
        
    def reload_templates(self):
        """Clear template cache and reload environment"""
        self._cache.clear()
        self.env = self._create_jinja_env()
        logger.info("Template cache cleared and environment reloaded")
        
    def add_template_dir(self, directory: Path):
        """Add a new template directory"""
        if directory not in self.template_dirs:
            self.template_dirs.append(directory)
            self.reload_templates()
            logger.info(f"Added template directory: {directory}")