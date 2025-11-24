import logging
import asyncio
from models import LogEvent
from db_conn import SessionLocalAsync
from sqlalchemy import insert

class DBLogHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        # Для совместимости с sync logging API — запускаем асинхронную запись через asyncio.create_task
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._log_to_db(record))
            else:
                loop.run_until_complete(self._log_to_db(record))
        except Exception:
            pass  # Не допускаем падения логгера

    async def _log_to_db(self, record):
        async with SessionLocalAsync() as session:
            stmt = insert(LogEvent).values(
                level=record.levelname,
                message=self.format(record),
                extra_data={
                    'module': record.module,
                    'funcName': record.funcName,
                    'lineno': record.lineno,
                    'pathname': record.pathname
                }
            )
            await session.execute(stmt)
            await session.commit()

# Настройка логгера
logger = logging.getLogger("service_logger")
logger.setLevel(logging.INFO)

# Формат логов
formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(module)s: %(message)s')

# Хендлер для БД
db_handler = DBLogHandler()
db_handler.setFormatter(formatter)
logger.addHandler(db_handler)

# Можно добавить и другие хендлеры (например, консоль):
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
