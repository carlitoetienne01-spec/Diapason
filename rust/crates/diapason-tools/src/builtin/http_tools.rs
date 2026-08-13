//! HTTP request tool.

use crate::traits::BaseTool;
use diapason_core::{DiapasonError, ToolResult, ToolSpec};
use diapason_security::ssrf::check_ssrf;
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::io::Read;

const MAX_RESPONSE_BYTES: u64 = 1_048_576;

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "http_request".into(),
    description: "Make an HTTP request".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "URL to request" },
            "method": { "type": "string", "description": "HTTP method (GET, POST, etc.)" },
            "body": { "type": "string", "description": "Request body (optional)" },
            "headers": { "type": "object", "description": "HTTP headers (optional)" }
        },
        "required": ["url"]
    }),
    category: "network".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: false,
    timeout_seconds: 30.0,
    required_capabilities: vec!["network:fetch".into()],
    metadata: HashMap::new(),
});

pub struct HttpRequestTool;

impl BaseTool for HttpRequestTool {
    fn tool_id(&self) -> &str {
        "http_request"
    }
    fn spec(&self) -> &ToolSpec {
        &SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, DiapasonError> {
        let url = params["url"].as_str().unwrap_or("");
        let method = params["method"].as_str().unwrap_or("GET").to_uppercase();

        if let Some(ssrf_error) = check_ssrf(url) {
            return Ok(ToolResult::failure("http_request", ssrf_error));
        }

        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            // Redirects must be checked hop-by-hop for SSRF. Until the native
            // client has a guarded resolver, refuse automatic redirects.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| DiapasonError::Io(std::io::Error::other(e.to_string())))?;

        let mut request = match method.as_str() {
            "POST" => client.post(url),
            "PUT" => client.put(url),
            "DELETE" => client.delete(url),
            "PATCH" => client.patch(url),
            "HEAD" => client.head(url),
            _ => client.get(url),
        };

        if let Some(body) = params["body"].as_str() {
            request = request.body(body.to_string());
        }

        if let Some(headers) = params["headers"].as_object() {
            for (k, v) in headers {
                if let Some(val) = v.as_str() {
                    request = request.header(k.as_str(), val);
                }
            }
        }

        match request.send() {
            Ok(resp) => {
                let status = resp.status().as_u16();
                let mut bytes = Vec::new();
                if let Err(error) = resp.take(MAX_RESPONSE_BYTES + 1).read_to_end(&mut bytes) {
                    return Ok(ToolResult::failure(
                        "http_request",
                        format!("Failed to read response: {error}"),
                    ));
                }
                let was_truncated = bytes.len() as u64 > MAX_RESPONSE_BYTES;
                bytes.truncate(MAX_RESPONSE_BYTES as usize);
                let mut body = String::from_utf8_lossy(&bytes).into_owned();
                if was_truncated {
                    body.push_str("\n\n[Response truncated at 1 MB]");
                }
                let content = format!("Status: {status}\n{body}");
                if status < 400 {
                    Ok(ToolResult::success("http_request", content))
                } else {
                    Ok(ToolResult::failure("http_request", content))
                }
            }
            Err(e) => Ok(ToolResult::failure(
                "http_request",
                format!("Request failed: {e}"),
            )),
        }
    }
}
