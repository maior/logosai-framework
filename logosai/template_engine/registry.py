"""
Template Registry for LogosAI

Manages template metadata and search functionality.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class TemplateMetadata:
    """Metadata for a template"""
    name: str
    category: str
    description: str
    required_params: List[str]
    optional_params: Dict[str, Any]
    tags: List[str]
    example_usage: Optional[str] = None
    version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TemplateMetadata':
        """Create from dictionary"""
        return cls(**data)


class TemplateRegistry:
    """Registry for template metadata and search"""
    
    def __init__(self, metadata_file: Optional[Path] = None):
        """
        Initialize the registry.
        
        Args:
            metadata_file: Optional path to metadata JSON file
        """
        self._templates: Dict[str, TemplateMetadata] = {}
        self.metadata_file = metadata_file
        
        if metadata_file and metadata_file.exists():
            self._load_metadata()
        else:
            self._initialize_default_metadata()
            
    def _initialize_default_metadata(self):
        """Initialize with default template metadata"""
        default_templates = [
            TemplateMetadata(
                name="base/basic_agent.py.jinja2",
                category="base",
                description="Basic LogosAI agent with standard structure",
                required_params=["agent_name", "agent_class_name", "description"],
                optional_params={
                    "dependencies": [],
                    "setup_steps": [],
                    "processing_logic": None,
                    "additional_methods": []
                },
                tags=["basic", "starter", "simple"],
                example_usage="""
engine.render("base/basic_agent.py.jinja2", {
    "agent_name": "DataProcessor",
    "agent_class_name": "DataProcessorAgent",
    "description": "Processes incoming data streams"
})
"""
            ),
            TemplateMetadata(
                name="base/async_agent.py.jinja2",
                category="base",
                description="Asynchronous agent for concurrent operations",
                required_params=["agent_name", "agent_class_name", "description"],
                optional_params={
                    "concurrent_tasks": 5,
                    "timeout": 30,
                    "retry_count": 3
                },
                tags=["async", "concurrent", "performance"]
            ),
            TemplateMetadata(
                name="base/workflow_agent.py.jinja2",
                category="base",
                description="Workflow orchestration agent",
                required_params=["agent_name", "agent_class_name", "description", "workflow_steps"],
                optional_params={
                    "parallel_execution": False,
                    "step_timeout": 60
                },
                tags=["workflow", "orchestration", "pipeline"]
            ),
            TemplateMetadata(
                name="patterns/singleton_agent.py.jinja2",
                category="patterns",
                description="Singleton pattern agent for single instance requirement",
                required_params=["agent_name", "agent_class_name", "description"],
                optional_params={},
                tags=["singleton", "pattern", "design-pattern"]
            ),
            TemplateMetadata(
                name="integrations/database_agent.py.jinja2",
                category="integrations",
                description="Database integration agent with connection pooling",
                required_params=["agent_name", "agent_class_name", "description", "db_config"],
                optional_params={
                    "pool_size": 10,
                    "max_overflow": 20,
                    "pool_timeout": 30
                },
                tags=["database", "integration", "sql", "persistence"]
            )
        ]
        
        for template in default_templates:
            self.register(template)
            
    def _load_metadata(self):
        """Load metadata from file"""
        try:
            with open(self.metadata_file, 'r') as f:
                data = json.load(f)
                
            for template_data in data.get('templates', []):
                metadata = TemplateMetadata.from_dict(template_data)
                self.register(metadata)
                
            logger.info(f"Loaded {len(self._templates)} templates from {self.metadata_file}")
            
        except Exception as e:
            logger.error(f"Failed to load metadata: {e}")
            self._initialize_default_metadata()
            
    def register(self, metadata: TemplateMetadata):
        """Register a template"""
        self._templates[metadata.name] = metadata
        logger.debug(f"Registered template: {metadata.name}")
        
    def get(self, template_name: str) -> Optional[TemplateMetadata]:
        """Get template metadata by name"""
        return self._templates.get(template_name)
        
    def search(self, query: Optional[str] = None, 
               category: Optional[str] = None,
               tags: Optional[List[str]] = None) -> List[TemplateMetadata]:
        """
        Search for templates.
        
        Args:
            query: Text search in name and description
            category: Filter by category
            tags: Filter by tags (ANY match)
            
        Returns:
            List of matching templates
        """
        results = list(self._templates.values())
        
        # Category filter
        if category:
            results = [t for t in results if t.category == category]
            
        # Tag filter
        if tags:
            results = [t for t in results 
                      if any(tag in t.tags for tag in tags)]
                      
        # Query search
        if query:
            query_lower = query.lower()
            results = [t for t in results
                      if query_lower in t.name.lower()
                      or query_lower in t.description.lower()
                      or any(query_lower in tag for tag in t.tags)]
                      
        return sorted(results, key=lambda t: t.name)
        
    def get_by_category(self, category: str) -> List[TemplateMetadata]:
        """Get all templates in a category"""
        return [t for t in self._templates.values() if t.category == category]
        
    def get_categories(self) -> List[str]:
        """Get all available categories"""
        categories = set(t.category for t in self._templates.values())
        return sorted(categories)
        
    def get_all_tags(self) -> List[str]:
        """Get all unique tags"""
        tags = set()
        for template in self._templates.values():
            tags.update(template.tags)
        return sorted(tags)
        
    def save_metadata(self, file_path: Optional[Path] = None):
        """Save metadata to file"""
        save_path = file_path or self.metadata_file
        
        if not save_path:
            logger.warning("No metadata file path specified")
            return
            
        data = {
            'version': '1.0.0',
            'templates': [t.to_dict() for t in self._templates.values()]
        }
        
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved metadata to {save_path}")
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")