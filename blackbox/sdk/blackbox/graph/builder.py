"""
Execution graph builder from events.
"""
from typing import List, Dict, Optional, Any
from blackbox.events.schema import ExecutionEvent, Run


class ExecutionNode:
    """Node in the execution graph."""
    
    def __init__(self, event: ExecutionEvent):
        self.event = event
        self.children: List[ExecutionNode] = []
        self.parent: Optional[ExecutionNode] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation."""
        return {
            "event_id": self.event.event_id,
            "component_name": self.event.component_name,
            "component_type": self.event.component_type,
            "status": self.event.status,
            "duration_ms": self.event.duration_ms,
            "children": [child.event.event_id for child in self.children],
        }


class ExecutionGraph:
    """
    Execution graph representing the structure of a run.
    """
    
    def __init__(self, run: Run, events: List[ExecutionEvent]):
        self.run = run
        self.events = sorted(events, key=lambda e: e.sequence_number)
        self.nodes: Dict[str, ExecutionNode] = {}
        self.root: Optional[ExecutionNode] = None
        self._build_graph()
    
    def _build_graph(self):
        """Build the graph from events."""
        # Create nodes
        for event in self.events:
            self.nodes[event.event_id] = ExecutionNode(event)
        
        # Build parent-child relationships
        for event in self.events:
            node = self.nodes[event.event_id]
            
            if event.parent_event_id and event.parent_event_id in self.nodes:
                parent_node = self.nodes[event.parent_event_id]
                node.parent = parent_node
                parent_node.children.append(node)
            elif event.parent_event_id is None:
                # Root node
                if self.root is None:
                    self.root = node
    
    def get_node(self, event_id: str) -> Optional[ExecutionNode]:
        """Get a node by event ID."""
        return self.nodes.get(event_id)
    
    def get_descendants(self, event_id: str) -> List[ExecutionNode]:
        """Get all descendants of a node."""
        node = self.nodes.get(event_id)
        if not node:
            return []
        
        descendants = []
        queue = [node]
        while queue:
            current = queue.pop(0)
            for child in current.children:
                descendants.append(child)
                queue.append(child)
        
        return descendants
    
    def get_ancestors(self, event_id: str) -> List[ExecutionNode]:
        """Get all ancestors of a node."""
        node = self.nodes.get(event_id)
        if not node:
            return []
        
        ancestors = []
        current = node.parent
        while current:
            ancestors.append(current)
            current = current.parent
        
        return ancestors
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert graph to dictionary representation."""
        return {
            "run_id": self.run.run_id,
            "status": self.run.status,
            "outcome": self.run.outcome,
            "event_count": len(self.events),
            "nodes": {
                event_id: node.to_dict()
                for event_id, node in self.nodes.items()
            },
            "root_event_id": self.root.event.event_id if self.root else None,
        }


def build_execution_graph(run: Run, events: List[ExecutionEvent]) -> ExecutionGraph:
    """
    Build an execution graph from a run and its events.
    
    Args:
        run: The run
        events: List of execution events
        
    Returns:
        ExecutionGraph representing the execution structure
    """
    return ExecutionGraph(run, events)
