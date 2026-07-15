import logging

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_fastapi_common.context import app_registry

from .config import get_settings
from .controllers.health import HealthController
from .controllers.national_id_dedup import NationalIdDedupController
from .services import get_background_worker

_config = get_settings()
_logger = logging.getLogger(__name__)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        logging.basicConfig(level=_config.log_level)

        app = app_registry.get()
        app.include_router(HealthController().router)
        app.include_router(NationalIdDedupController().router)
        app.add_event_handler("startup", get_background_worker().start)
        app.add_event_handler("shutdown", get_background_worker().stop)

        _logger.info("%s initialized", _config.openapi_title)
