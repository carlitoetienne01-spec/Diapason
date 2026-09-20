"""Tests for CLI log configuration."""

from __future__ import annotations

import logging

from diapason.cli.log_config import setup_logging


class TestSetupLogging:
    def test_default_level_is_warning(self):
        logger = setup_logging(verbose=False, quiet=False)
        assert logger.level == logging.WARNING

    def test_verbose_sets_debug(self):
        logger = setup_logging(verbose=True, quiet=False)
        assert logger.level == logging.DEBUG

    def test_quiet_sets_error(self):
        logger = setup_logging(verbose=False, quiet=True)
        assert logger.level == logging.ERROR

    def test_returns_logger(self):
        logger = setup_logging(verbose=False, quiet=False)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "diapason"

    def test_la_mesure_du_chat_parle_en_info_par_defaut(self):
        """Sans cette règle, chat_performance restait sous le niveau WARNING
        du logger racine et le journal du serveur ne portait aucune latence."""
        setup_logging(verbose=False, quiet=False)
        mesure = logging.getLogger("diapason.telemetry.chat_latency")
        assert mesure.isEnabledFor(logging.INFO), "la ligne doit atteindre le journal"
        voix = logging.getLogger("diapason.speech.realtime.local_voice")
        assert voix.isEnabledFor(logging.INFO)
        chauffe = logging.getLogger("diapason.server.prechauffage")
        assert chauffe.isEnabledFor(logging.INFO)

    def test_log_file_handler_on_verbose(self, tmp_path):
        log_file = tmp_path / "cli.log"
        logger = setup_logging(verbose=True, quiet=False, log_file=log_file)
        # Should have at least one file handler
        file_handlers = [h for h in logger.handlers if hasattr(h, "baseFilename")]
        assert len(file_handlers) >= 1
        # Clean up
        for h in logger.handlers[:]:
            logger.removeHandler(h)
            h.close()
