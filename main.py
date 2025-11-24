import asyncio

from stock_service import (
    cancel_orders_from_archive,
    cancel_orders_from_returned_archive,
    process_new_orders,
    process_orders,
    save_waybill_links
)
from logger_conf import logger
from datetime import datetime

MAX_ATTEMPTS = 5
SLEEP_SECONDS = 10

async def main():
    start_time = datetime.now()
    logger.info(f"Script started at {start_time}")
    try:
        # 1. Сначала отменяем архивные заказы
        try:
            await cancel_orders_from_returned_archive()
            await cancel_orders_from_archive()
            # await process_orders()
        except Exception as e:
            logger.error(f"Error in cancel_orders_from_archive: {e}")

        # 2. Обработка новых заказов
        new_orders_result = await process_new_orders()
        logger.info(f"process_new_orders result: {new_orders_result}")

        if new_orders_result is None or (isinstance(new_orders_result, dict) and new_orders_result.get("failed")):
            logger.error(f"Ошибка при обработке новых заказов: {new_orders_result}")
            return

        # 3. Если есть новые заказы, пробуем обработать их с повторными попытками
        if new_orders_result and new_orders_result.get("success"):
            new_order_ids = set(new_orders_result.get("success", []))
            for attempt in range(1, MAX_ATTEMPTS + 1):
                orders_result = await process_orders()
                logger.info(f"process_orders attempt {attempt}: {orders_result}")
                if orders_result and orders_result.get("success"):
                    break
                # Проверяем отмену перед следующей попыткой
                canceled_ids = await cancel_orders_from_archive() or []
                logger.info(f"cancel_orders_from_archive attempt {attempt}: {canceled_ids}")
                if any(order_id in canceled_ids for order_id in new_order_ids):
                    logger.warning("Один из новых заказов был отменён клиентом. Останавливаем попытки.")
                    return
                await asyncio.sleep(SLEEP_SECONDS)
            else:
                logger.warning("process_orders не вернул результат после повторных попыток")

            for attempt in range(1, MAX_ATTEMPTS + 1):
                waybill_result = await save_waybill_links()
                logger.info(f"save_waybill_links attempt {attempt}: {waybill_result}")
                if waybill_result and any(order_id in waybill_result for order_id in new_order_ids):
                    break
                # Проверяем отмену перед следующей попыткой
                canceled_ids = await cancel_orders_from_archive() or []
                logger.info(f"cancel_orders_from_archive (waybill) attempt {attempt}: {canceled_ids}")
                if any(order_id in canceled_ids for order_id in new_order_ids):
                    logger.warning("Один из новых заказов был отменён клиентом (waybill). Останавливаем попытки.")
                    return
                await asyncio.sleep(SLEEP_SECONDS)
            else:
                logger.warning("save_waybill_links не вернул результат после повторных попыток")
        else:
            logger.info("Нет новых заказов для обработки")

    except Exception as e:
        logger.error(f"Critical error in main process: {e}")
        raise
    finally:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"Script finished at {end_time}, duration: {duration} seconds")

if __name__ == "__main__":
    asyncio.run(main())


