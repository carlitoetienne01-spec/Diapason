"""Workflow engine — DAG-based multi-agent pipelines."""

from diapason.workflow.builder import WorkflowBuilder
from diapason.workflow.engine import WorkflowEngine
from diapason.workflow.graph import WorkflowGraph
from diapason.workflow.loader import load_workflow
from diapason.workflow.types import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowResult,
    WorkflowStepResult,
)

__all__ = [
    "WorkflowBuilder",
    "WorkflowEdge",
    "WorkflowEngine",
    "WorkflowGraph",
    "WorkflowNode",
    "WorkflowResult",
    "WorkflowStepResult",
    "load_workflow",
]
