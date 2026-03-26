"""Constants for the Hamster MCP integration."""

from homeassistant.const import Platform

DOMAIN = "hamster"
DEFAULT_IDLE_TIMEOUT: float = 1800.0  # 30 minutes
DEFAULT_ENABLE_SERVICES_GROUP: bool = True
DEFAULT_AUTO_FETCH_DOCS: bool = True
DEFAULT_DOCS_GIT_REF: str = "master"
DEFAULT_DOCS_URL_TEMPLATE: str = (
    "https://raw.githubusercontent.com/"
    "home-assistant/developers.home-assistant/"
    "{ref}/docs/api/websocket.md"
)
PLATFORMS: list[Platform] = [Platform.BUTTON]
