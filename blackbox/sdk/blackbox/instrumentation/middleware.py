"""
FastAPI middleware for Black Box instrumentation.
"""
from datetime import datetime
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
import uuid

from blackbox.events.schema import Run, RunStatus, RunOutcome
from blackbox.instrumentation.context import BlackBoxContext, set_current_run_id
from blackbox.storage.interface import StorageBackend


class BlackBoxMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for automatic run tracking.
    """
    
    def __init__(self, app, storage: StorageBackend = None):
        super().__init__(app)
        self.storage = storage
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with Black Box instrumentation.
        
        Args:
            request: Incoming request
            call_next: Next middleware/handler
            
        Returns:
            Response
        """
        # Create run context
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        
        # Extract task input from request
        task_input = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "headers": dict(request.headers),
        }
        
        # Try to get request body if available
        try:
            if request.method in ["POST", "PUT", "PATCH"]:
                # Note: This consumes the body, may need adjustment
                pass
        except:
            pass
        
        # Create run
        run = Run(
            run_id=run_id,
            task_input=task_input,
            status=RunStatus.RUNNING,
            outcome=RunOutcome.UNKNOWN,
            started_at=datetime.utcnow(),
        )
        
        # Store run
        if self.storage:
            try:
                self.storage.store_run(run)
            except Exception as e:
                print(f"Warning: Failed to store run: {e}")
        
        # Set context
        set_current_run_id(run_id)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Update run status
            run.status = RunStatus.COMPLETED
            run.finished_at = datetime.utcnow()
            run.duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000
            
            # Determine outcome based on status code
            if 200 <= response.status_code < 300:
                run.outcome = RunOutcome.SUCCESS
            else:
                run.outcome = RunOutcome.FAILURE
            
            # Update in storage
            if self.storage:
                try:
                    self.storage.update_run(run_id, {
                        'status': run.status,
                        'outcome': run.outcome,
                        'finished_at': run.finished_at,
                        'duration_ms': run.duration_ms,
                    })
                except Exception as e:
                    print(f"Warning: Failed to update run: {e}")
            
            return response
        
        except Exception as exc:
            # Update run with error
            run.status = RunStatus.FAILED
            run.outcome = RunOutcome.FAILURE
            run.finished_at = datetime.utcnow()
            run.duration_ms = (run.finished_at - run.started_at).total_seconds() * 1000
            
            if self.storage:
                try:
                    self.storage.update_run(run_id, {
                        'status': run.status,
                        'outcome': run.outcome,
                        'finished_at': run.finished_at,
                        'duration_ms': run.duration_ms,
                    })
                except Exception as e:
                    print(f"Warning: Failed to update run: {e}")
            
            # Re-raise exception
            raise
