"""Tests for shell execution through the managed Python implementation."""

from __future__ import annotations

import importlib
import os
import shlex
import sys

from diapason.core import get_python_executable
from diapason.tools.shell_exec import ShellExecTool


class TestShellExecTool:
    def test_registered_via_tools_package_import(self):
        import diapason.tools as tools_pkg
        from diapason.core.registry import ToolRegistry

        sys.modules.pop("diapason.tools.shell_exec", None)
        importlib.reload(tools_pkg)
        assert ToolRegistry.contains("shell_exec")

    def test_spec(self):
        tool = ShellExecTool()
        assert tool.spec.name == "shell_exec"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 60.0
        assert "code:execute" in tool.spec.required_capabilities

    def test_no_command(self):
        result = ShellExecTool().execute(command="")
        assert result.success is False
        assert "No command" in result.content

    def test_simple_echo(self):
        result = ShellExecTool().execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.content
        assert "=== STDOUT ===" in result.content

    def test_capture_stderr(self):
        result = ShellExecTool().execute(command="echo error_msg >&2")
        assert result.success is True
        assert "error_msg" in result.content
        assert "=== STDERR ===" in result.content

    def test_timeout_exceeded(self):
        python = shlex.quote(get_python_executable())
        result = ShellExecTool().execute(
            command=f"{python} -c 'import time; time.sleep(60)'",
            timeout=1,
        )
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_capped_at_max(self):
        result = ShellExecTool().execute(command="echo ok", timeout=999)
        assert result.success is True
        assert result.metadata["timeout_used"] == 300

    def test_working_dir(self, tmp_path):
        result = ShellExecTool().execute(command="pwd", working_dir=str(tmp_path))
        assert result.success is True
        assert str(tmp_path) in result.content
        assert result.metadata["working_dir"] == str(tmp_path)

    def test_working_dir_validation(self, tmp_path):
        missing = ShellExecTool().execute(
            command="echo hi", working_dir="/nonexistent/path"
        )
        assert missing.success is False
        assert "does not exist" in missing.content

        file_path = tmp_path / "file.txt"
        file_path.write_text("data", encoding="utf-8")
        not_directory = ShellExecTool().execute(
            command="echo hi", working_dir=str(file_path)
        )
        assert not_directory.success is False
        assert "not a directory" in not_directory.content

    def test_environment_is_minimal_and_passthrough_is_explicit(self):
        marker = "DIAPASON_TEST_SECRET_12345"
        os.environ[marker] = "allowed_value"
        try:
            hidden = ShellExecTool().execute(command=f'printf %s "${marker}"')
            assert hidden.success is True
            assert "allowed_value" not in hidden.content

            visible = ShellExecTool().execute(
                command=f'printf %s "${marker}"',
                env_passthrough=[marker],
            )
            assert visible.success is True
            assert "allowed_value" in visible.content
        finally:
            os.environ.pop(marker, None)

    def test_nonzero_returncode(self):
        result = ShellExecTool().execute(command="exit 42")
        assert result.success is False
        assert result.metadata["returncode"] == 42

    def test_max_output_truncation(self):
        python = shlex.quote(get_python_executable())
        result = ShellExecTool().execute(command=f"{python} -c \"print('A' * 200000)\"")
        assert "truncated" in result.content
        assert len(result.content) < 200_000

    def test_no_output(self):
        result = ShellExecTool().execute(command="true")
        assert result.success is True
        assert result.content == "(no output)"

    def test_default_timeout_metadata(self):
        result = ShellExecTool().execute(command="echo ok")
        assert result.metadata["timeout_used"] == 30

    def test_to_openai_function(self):
        function = ShellExecTool().to_openai_function()
        assert function["type"] == "function"
        assert function["function"]["name"] == "shell_exec"
