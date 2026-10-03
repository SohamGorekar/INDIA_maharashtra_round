"""
Base adapter interface for framework integration.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
from blackbox.events.schema import Run, SideEffectType


class AgentAdapter(ABC):
    """
    Base adapter for integrating Black Box with different agent frameworks.
    """
    
    @abstractmethod
    def serialize_state(self, state: Any) -> Dict[str, Any]:
        """
        Serialize framework-specific state to JSON-compatible dict.
        
        Args:
            state: Framework-specific state object
            
        Returns:
            JSON-serializable dictionary
        """
        pass
    
    @abstractmethod
    def restore_state(self, serialized_state: Dict[str, Any]) -> Any:
        """
        Restore framework-specific state from serialized form.
        
        Args:
            serialized_state: Serialized state dictionary
            
        Returns:
            Framework-specific state object
        """
        pass
    
    @abstractmethod
    def classify_side_effect(self, component: Any) -> SideEffectType:
        """
        Classify the side effect type of a component.
        
        Args:
            component: Framework-specific component
            
        Returns:
            Side effect classification
        """
        pass
    
    @abstractmethod
    def evaluate_outcome(self, run: Run) -> bool:
        """
        Evaluate if a run was successful.
        
        Args:
            run: The run to evaluate
            
        Returns:
            True if successful, False otherwise
        """
        pass


class CustomPythonAdapter(AgentAdapter):
    """
    Adapter for custom Python agent systems.
    """
    
    def serialize_state(self, state: Any) -> Dict[str, Any]:
        """Serialize Python state."""
        if isinstance(state, dict):
            return state
        elif hasattr(state, '__dict__'):
            return state.__dict__
        else:
            return {"state": str(state)}
    
    def restore_state(self, serialized_state: Dict[str, Any]) -> Any:
        """Restore Python state."""
        return serialized_state
    
    def classify_side_effect(self, component: Any) -> SideEffectType:
        """Classify side effect."""
        # Default classification
        component_name = getattr(component, '__name__', str(component)).lower()
        
        if any(keyword in component_name for keyword in ['write', 'update', 'delete', 'create']):
            return SideEffectType.WRITE
        elif any(keyword in component_name for keyword in ['api', 'http', 'request', 'email', 'send']):
            return SideEffectType.EXTERNAL_SIDE_EFFECT
        else:
            return SideEffectType.READ
    
    def evaluate_outcome(self, run: Run) -> bool:
        """Evaluate outcome."""
        return run.outcome == "SUCCESS"
