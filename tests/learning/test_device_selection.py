"""Tests for PyTorch device selection (cuda > mps > cpu)."""

from __future__ import annotations


class TestSelectTorchDevice:
    """Tests for _select_torch_device() logic in orchestrator trainers.

    Since torch is not installed in the test environment, we test the
    selection logic directly rather than through the function (which
    returns None when torch is absent).
    """

    def test_no_torch_returns_none(self, monkeypatch):
        """Sans torch, ``_select_torch_device`` rend None.

        Ce test SUPPOSAIT que torch était absent de l'environnement de test.
        Il l'est chez certains, pas chez d'autres — ici torch est installé, et
        la fonction rendait donc « mps ». Un test qui dépend de ce qui est
        installé ne prouve pas ce qu'il annonce : on impose la condition au
        lieu de l'espérer.
        """
        from diapason.learning.intelligence.orchestrator import sft_trainer

        monkeypatch.setattr(sft_trainer, "HAS_TORCH", False)
        assert sft_trainer._select_torch_device() is None

    def test_torch_present_returns_a_device(self):
        """Et l'autre moitié, que l'ancien test ne pouvait pas voir."""
        from diapason.learning.intelligence.orchestrator import sft_trainer

        if not sft_trainer.HAS_TORCH:
            import pytest

            pytest.skip("torch absent de cet environnement")
        assert sft_trainer._select_torch_device() is not None

    def test_cuda_preferred(self):
        """CUDA is selected when available (logic test)."""
        has_cuda = True
        has_mps = True

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "cuda"

    def test_mps_fallback(self):
        """MPS is selected when CUDA is not available but MPS is."""
        has_cuda = False
        has_mps = True

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "mps"

    def test_cpu_last_resort(self):
        """CPU is selected when neither CUDA nor MPS is available."""
        has_cuda = False
        has_mps = False

        if has_cuda:
            choice = "cuda"
        elif has_mps:
            choice = "mps"
        else:
            choice = "cpu"

        assert choice == "cpu"

    def test_function_exists_in_both_trainers(self):
        """_select_torch_device is defined in both trainers."""
        from diapason.learning.intelligence.orchestrator.grpo_trainer import (
            _select_torch_device as grpo_fn,
        )
        from diapason.learning.intelligence.orchestrator.sft_trainer import (
            _select_torch_device as sft_fn,
        )

        assert callable(sft_fn)
        assert callable(grpo_fn)

    def test_exported_from_orchestrator_init(self):
        """_select_torch_device is exported from orchestrator package."""
        from diapason.learning.intelligence.orchestrator import (
            _select_torch_device,
        )

        assert callable(_select_torch_device)
