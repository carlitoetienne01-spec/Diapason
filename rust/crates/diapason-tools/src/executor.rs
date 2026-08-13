//! ToolExecutor — central dispatch with RBAC, taint, timeout.

use crate::builtin::BuiltinTool;
use crate::traits::BaseTool;
use diapason_core::error::{DiapasonError, ToolError};
use diapason_core::{EventBus, EventType, ToolResult};
use diapason_security::capabilities::CapabilityPolicy;
use diapason_security::taint::{check_taint, TaintSet};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

pub struct ToolExecutor {
    tools: HashMap<String, BuiltinTool>,
    capability_policy: Option<CapabilityPolicy>,
    bus: Option<Arc<EventBus>>,
    default_timeout: Duration,
}

impl ToolExecutor {
    pub fn new(capability_policy: Option<CapabilityPolicy>, bus: Option<Arc<EventBus>>) -> Self {
        Self {
            tools: HashMap::new(),
            capability_policy,
            bus,
            default_timeout: Duration::from_secs(30),
        }
    }

    pub fn register(&mut self, tool: BuiltinTool) {
        let id = tool.tool_id().to_string();
        self.tools.insert(id, tool);
    }

    pub fn get_tool(&self, name: &str) -> Option<&BuiltinTool> {
        self.tools.get(name)
    }

    pub fn list_tools(&self) -> Vec<String> {
        self.tools.keys().cloned().collect()
    }

    pub fn tool_specs(&self) -> Vec<Value> {
        self.tools
            .values()
            .map(|t| t.to_openai_function())
            .collect()
    }

    pub fn execute(
        &self,
        tool_name: &str,
        params: &Value,
        agent_id: Option<&str>,
        taint: Option<&TaintSet>,
    ) -> Result<ToolResult, DiapasonError> {
        let tool = self
            .tools
            .get(tool_name)
            .ok_or_else(|| DiapasonError::Tool(ToolError::NotFound(tool_name.to_string())))?;

        let spec = tool.spec();

        // Native dispatch has no approval callback. Mutating tools must stop
        // here instead of silently treating the absence of a UI as consent.
        if spec.requires_confirmation {
            return Err(DiapasonError::Tool(ToolError::ConfirmationRequired(
                tool_name.to_string(),
            )));
        }

        // RBAC is fail-closed: a capability-bearing tool cannot run when the
        // caller omitted either the policy or the agent identity.
        if !spec.required_capabilities.is_empty() {
            let aid = agent_id.ok_or_else(|| {
                DiapasonError::Tool(ToolError::CapabilityDenied(
                    "<missing>".to_string(),
                    format!("agent identity (tool: {tool_name})"),
                ))
            })?;
            let policy = self.capability_policy.as_ref().ok_or_else(|| {
                DiapasonError::Tool(ToolError::CapabilityDenied(
                    aid.to_string(),
                    format!("capability policy unavailable (tool: {tool_name})"),
                ))
            })?;
            for cap in &spec.required_capabilities {
                if !policy.check(aid, cap, tool_name) {
                    return Err(DiapasonError::Tool(ToolError::CapabilityDenied(
                        aid.to_string(),
                        format!("{cap} (tool: {tool_name})"),
                    )));
                }
            }
        }

        // Taint check
        if let Some(taint_set) = taint {
            if let Some(violation) = check_taint(tool_name, taint_set) {
                return Err(DiapasonError::Tool(ToolError::TaintViolation(
                    tool_name.to_string(),
                    violation,
                )));
            }
        }

        // Emit start event
        if let Some(ref bus) = self.bus {
            let mut data = HashMap::new();
            data.insert(
                "tool_name".to_string(),
                Value::String(tool_name.to_string()),
            );
            bus.publish(EventType::ToolCallStart, data);
        }

        let start = std::time::Instant::now();
        let timeout = Duration::from_secs_f64(tool.spec().timeout_seconds);
        let timeout = if timeout.is_zero() {
            self.default_timeout
        } else {
            timeout
        };

        let result = tool.execute(params);
        let elapsed = start.elapsed();

        if elapsed > timeout {
            if let Some(ref bus) = self.bus {
                let mut data = HashMap::new();
                data.insert(
                    "tool_name".to_string(),
                    Value::String(tool_name.to_string()),
                );
                bus.publish(EventType::ToolTimeout, data);
            }
            return Err(DiapasonError::Tool(ToolError::Timeout(
                timeout.as_secs_f64(),
                tool_name.to_string(),
            )));
        }

        // Emit end event
        if let Some(ref bus) = self.bus {
            let mut data = HashMap::new();
            data.insert(
                "tool_name".to_string(),
                Value::String(tool_name.to_string()),
            );
            data.insert(
                "duration_seconds".to_string(),
                Value::Number(serde_json::Number::from_f64(elapsed.as_secs_f64()).unwrap()),
            );
            bus.publish(EventType::ToolCallEnd, data);
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_executor_register_and_execute() {
        let mut exec = ToolExecutor::new(None, None);
        exec.register(BuiltinTool::Calculator(
            crate::builtin::calculator::CalculatorTool,
        ));
        let result = exec
            .execute(
                "calculator",
                &serde_json::json!({"expression": "2+2"}),
                None,
                None,
            )
            .unwrap();
        assert!(result.success);
    }

    #[test]
    fn test_executor_tool_not_found() {
        let exec = ToolExecutor::new(None, None);
        let err = exec
            .execute("nonexistent", &serde_json::json!({}), None, None)
            .unwrap_err();
        assert!(matches!(err, DiapasonError::Tool(ToolError::NotFound(_))));
    }

    #[test]
    fn test_executor_denies_capability_tool_without_security_context() {
        let mut exec = ToolExecutor::new(None, None);
        exec.register(BuiltinTool::FileRead(
            crate::builtin::file_tools::FileReadTool,
        ));
        let err = exec
            .execute(
                "file_read",
                &serde_json::json!({"path": "Cargo.toml"}),
                None,
                None,
            )
            .unwrap_err();
        assert!(matches!(
            err,
            DiapasonError::Tool(ToolError::CapabilityDenied(_, _))
        ));
    }

    #[test]
    fn test_executor_denies_confirmation_tool_without_approval_channel() {
        let mut exec = ToolExecutor::new(None, None);
        exec.register(BuiltinTool::ShellExec(crate::builtin::shell::ShellExecTool));
        let err = exec
            .execute(
                "shell_exec",
                &serde_json::json!({"command": "echo unsafe"}),
                None,
                None,
            )
            .unwrap_err();
        assert!(matches!(
            err,
            DiapasonError::Tool(ToolError::ConfirmationRequired(_))
        ));
    }
}
