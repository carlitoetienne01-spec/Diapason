"""Data source connectors for Deep Research."""

from diapason.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from diapason.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import diapason.connectors.obsidian  # noqa: F401

try:
    import diapason.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import diapason.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import diapason.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import diapason.connectors.news_rss  # noqa: F401
except ImportError:
    pass
