//! MemoryBackend trait for all storage backends.

use diapason_core::{DiapasonError, RetrievalResult};
use serde_json::Value;

pub trait MemoryBackend: Send + Sync {
    fn backend_id(&self) -> &str;
    fn store(
        &self,
        content: &str,
        source: &str,
        metadata: Option<&Value>,
    ) -> Result<String, DiapasonError>;
    fn retrieve(
        &self,
        query: &str,
        top_k: usize,
    ) -> Result<Vec<RetrievalResult>, DiapasonError>;
    fn delete(&self, doc_id: &str) -> Result<bool, DiapasonError>;
    fn clear(&self) -> Result<(), DiapasonError>;
    fn count(&self) -> Result<usize, DiapasonError>;
}
