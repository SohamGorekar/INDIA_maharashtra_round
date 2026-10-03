"""
LangGraph adapter for Black Box SDK.

Translates the customer support agent's LangGraph execution model
into Black Box events and manages state serialization.
"""
import sys
from pathlib import Path

# Add Black Box SDK to path
SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

from typing import Any, Dict
from blackbox.adapters.base import AgentAdapter
from blackbox.events.schema import SideEffectType, RunOutcome


class LangGraphAdapter(AgentAdapter):
    """
    Adapter for LangGraph-based customer support agent.
    
    Handles state serialization and side-effect classification specific
    to the customer support agent architecture.
    """
    
    def serialize_state(self, state: Any) -> Dict[str, Any]:
        """
        Serialize LangGraph AgentState to JSON-compatible dict.
        
        Args:
            state: AgentState dictionary
            
        Returns:
            JSON-serializable state
        """
        if not isinstance(state, dict):
            return {"state": str(state)}
        
        # AgentState is already dict-based, but messages need special handling
        serialized = {}
        
        for key, value in state.items():
            if key == "messages":
                # Convert LangChain messages to dicts
                try:
                    from langchain_core.messages import messages_to_dict
                    serialized[key] = messages_to_dict(value)
                except Exception:
                    # Fallback if conversion fails
                    serialized[key] = [str(m) for m in value]
            elif isinstance(value, (str, int, float, bool, type(None))):
                serialized[key] = value
            elif isinstance(value, (list, dict)):
                serialized[key] = value
            else:
                serialized[key] = str(value)
        
        return serialized
    
    def restore_state(self, serialized_state: Dict[str, Any]) -> Any:
        """
        Restore LangGraph AgentState from serialized form.
        
        Args:
            serialized_state: Serialized state dictionary
            
        Returns:
            Restored AgentState
        """
        restored = dict(serialized_state)
        
        # Restore messages from dicts
        if "messages" in restored:
            try:
                from langchain_core.messages import messages_from_dict
                restored["messages"] = messages_from_dict(restored["messages"])
            except Exception:
                # Keep as-is if restoration fails
                pass
        
        return restored
    
    def classify_side_effect(self, component: Any) -> SideEffectType:
        """
        Classify side effects for customer support agent components.
        
        Args:
            component: Component to classify
            
        Returns:
            Side effect classification
        """
        # Get component name
        if hasattr(component, "name"):
            name = component.name.lower()
        elif hasattr(component, "__name__"):
            name = component.__name__.lower()
        else:
            name = str(component).lower()
        
        # Classify based on tool/function name
        # Write operations
        if any(keyword in name for keyword in ["take_action", "update", "delete", "create", "insert"]):
            return SideEffectType.WRITE
        
        # External side effects (emails, payments, etc.)
        if any(keyword in name for keyword in ["send", "email", "payment", "notify"]):
            return SideEffectType.EXTERNAL_SIDE_EFFECT
        
        # Default to READ for queries and LLM calls
        return SideEffectType.READ
    
    def evaluate_outcome(self, run: Any) -> bool:
        """
        Evaluate if a run was successful based on customer support criteria.
        
        Args:
            run: Run object
            
        Returns:
            True if successful, False otherwise
        """
        # Check outcome field
        if hasattr(run, "outcome"):
            return run.outcome in ["SUCCESS", RunOutcome.SUCCESS]
        
        # Fallback to status check
        if hasattr(run, "status"):
            return run.status not in ["failed", "error"]
        
        return True
    
    def map_decision_to_outcome(self, decision: str, expected_decision: str = None) -> RunOutcome:
        """
        Map agent decision to Black Box outcome.
        
        Args:
            decision: Agent's decision (APPROVE, DENY, etc.)
            expected_decision: Expected decision if known
            
        Returns:
            RunOutcome enum value
        """
        if not decision:
            return RunOutcome.FAILURE
        
        # If we have expected decision, check correctness
        if expected_decision:
            if decision == expected_decision:
                return RunOutcome.SUCCESS
            else:
                return RunOutcome.FAILURE
        
        # Otherwise, any valid decision is success
        valid_decisions = {"APPROVE", "DENY", "REQUEST_PHOTO", "ESCALATE"}
        if decision in valid_decisions:
            return RunOutcome.SUCCESS
        
        return RunOutcome.UNKNOWN
