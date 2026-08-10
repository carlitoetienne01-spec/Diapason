"""Intelligence learning — model fine-tuning via SFT and GRPO."""

from __future__ import annotations

# Import trainers so their @LearningRegistry.register decorators execute.
try:
    from diapason.learning.intelligence import sft_trainer as _sft  # noqa: F401
except ImportError:
    pass
try:
    from diapason.learning.intelligence import grpo_trainer as _grpo  # noqa: F401
except ImportError:
    pass
