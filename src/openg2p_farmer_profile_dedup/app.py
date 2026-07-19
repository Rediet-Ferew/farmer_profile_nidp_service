import logging

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_fastapi_common.context import app_registry

from .config import get_settings
from .controllers.farmer_approval import FarmerApprovalController
from .controllers.health import HealthController
from .controllers.mock_nidp import MockNidpController
from .controllers.national_id_dedup import NationalIdDedupController
from .services import get_background_worker, get_farmer_approval_worker

_config = get_settings()
_logger = logging.getLogger(__name__)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        logging.basicConfig(level=_config.log_level)

        app = app_registry.get()
        app.include_router(HealthController().router)
        app.include_router(NationalIdDedupController().router)
        app.include_router(FarmerApprovalController().router)
        if _config.mock_nidp_enabled:
            app.include_router(MockNidpController().router)
            _logger.warning("Internal mock NIDP endpoint is enabled.")

        _logger.info("%s initialized", _config.openapi_title)

    async def fastapi_app_startup(self, app):
        await super().fastapi_app_startup(app)
        worker = get_background_worker()
        if _config.service_db_auto_migrate:
            await worker.service.migrate_service_db()
        worker.start()
        get_farmer_approval_worker().start()

    async def fastapi_app_shutdown(self, app):
        await get_farmer_approval_worker().stop()
        await get_background_worker().stop()
        await super().fastapi_app_shutdown(app)
