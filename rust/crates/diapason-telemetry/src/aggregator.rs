//! TelemetryAggregator — read-only SQL aggregation queries.

use crate::store::TelemetryStore;
use diapason_core::DiapasonError;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AggregateStats {
    pub total_requests: usize,
    pub total_tokens: i64,
    pub avg_latency: f64,
    pub avg_throughput: f64,
    pub total_cost: f64,
    pub total_energy: f64,
}

pub struct TelemetryAggregator;

impl TelemetryAggregator {
    pub fn stats(_store: &TelemetryStore) -> Result<AggregateStats, DiapasonError> {
        Ok(AggregateStats::default())
    }
}
