"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from diapason.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import diapason.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.docker_shell_exec  # noqa: F401
    import diapason.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import diapason.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.digest_collect  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.desktop_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.voice_mac_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.screen_vision_tools  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.succes_tasks  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.succes_workspace  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.succes_continuity  # noqa: F401
except ImportError:
    pass

try:
    import diapason.tools.mesh_tools  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
