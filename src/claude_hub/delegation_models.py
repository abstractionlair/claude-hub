"""Pydantic models for delegation API endpoints."""

from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


# Workspace endpoints
class CreateWorkspaceParams(BaseModel):
    """Parameters for creating a workspace."""
    project: str
    agent_id: str
    parent_id: Optional[str] = None
    deadline: Optional[datetime] = None
    max_memory_mb: Optional[int] = None
    max_agents: Optional[int] = None
    max_iterations: Optional[int] = None


class CreateWorkspaceResponse(BaseModel):
    """Response from creating a workspace."""
    workspace_path: str
    agent_dir_name: str


class ListChildrenParams(BaseModel):
    """Parameters for listing child workspaces."""
    project: str
    parent_agent_id: str


class ListChildrenResponse(BaseModel):
    """Response from listing children."""
    children: List[str]


# Scheduling endpoints
class ScheduleWakeAtParams(BaseModel):
    """Parameters for schedule_wake_at."""
    session_id: str
    time: datetime
    prompt: str
    deadline: Optional[datetime] = None
    max_memory_mb: Optional[int] = None
    max_agents: Optional[int] = None
    max_iterations: Optional[int] = None


class ScheduleWakeEveryParams(BaseModel):
    """Parameters for schedule_wake_every."""
    session_id: str
    interval_seconds: int
    prompt: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deadline: Optional[datetime] = None
    max_memory_mb: Optional[int] = None
    max_agents: Optional[int] = None
    max_iterations: Optional[int] = None


class ScheduleResponse(BaseModel):
    """Response from scheduling operations."""
    schedule_id: str


class ListSchedulesParams(BaseModel):
    """Parameters for list_schedules."""
    session_id: Optional[str] = None


class ScheduleInfo(BaseModel):
    """Information about a schedule."""
    schedule_id: str
    session_id: str
    next_wake: datetime
    interval_seconds: Optional[int]
    prompt: str
    end_time: Optional[datetime]
    created_at: datetime


class ListSchedulesResponse(BaseModel):
    """Response from list_schedules."""
    schedules: List[ScheduleInfo]


class CancelScheduleParams(BaseModel):
    """Parameters for cancel_schedule."""
    schedule_id: str


class CancelScheduleResponse(BaseModel):
    """Response from cancel_schedule."""
    success: bool


# Handoff endpoints
class WriteHandoffParams(BaseModel):
    """Parameters for write_handoff."""
    project: str
    agent_id: str
    parent_id: Optional[str] = None
    summary: str
    status: str
    findings: Optional[List[str]] = None
    files_changed: Optional[List[str]] = None
    questions: Optional[List[str]] = None
    recommendations: Optional[str] = None


class WriteHandoffResponse(BaseModel):
    """Response from write_handoff."""
    handoff_path: str


class ReadHandoffParams(BaseModel):
    """Parameters for read_handoff."""
    project: str
    agent_id: str
    parent_id: Optional[str] = None


class HandoffInfo(BaseModel):
    """Handoff information."""
    status: str
    summary: str
    started_at: datetime
    last_updated: datetime
    findings: List[str]
    files_changed: List[str]
    questions: List[str]
    recommendations: Optional[str]


class ReadHandoffResponse(BaseModel):
    """Response from read_handoff."""
    handoff: Optional[HandoffInfo]
    markdown: Optional[str]


class ListHandoffsParams(BaseModel):
    """Parameters for list_handoffs."""
    project: str


class ListHandoffsResponse(BaseModel):
    """Response from list_handoffs."""
    handoffs: Dict[str, HandoffInfo]
