import asyncio
import traceback
from sqlalchemy import insert, update
from db_conn import SessionLocalAsync
from logger_conf import logger
from kaspi import (
    get_new_archive,
    get_new_orders,
    accept_order,
    get_kaspi_delivery,
    create_invoice,
    get_order_entries,
    get_returned_archive,
)
from stock_repository import get_stock_quantity, mark_order_as_canceled, get_order_products, \
    is_order_processed, save_order, process_product_cancellation, is_order_canceled, update_stock_quantity_and_log
from datetime import datetime
from models import LogEvent, KaspiSoldProduct, KaspiOrder

CONCURRENT_ORDER_LIMIT = 5  # Можно вынести в настройки

async def process_new_orders():
    """Processes new orders asynchronously."""
    try:
        new_orders = await get_new_orders()

        if not new_orders:
            return {"processed": 0, "success": [], "failed": [], "skipped": []}

        processed, success, failed, skipped = 0, [], [], []
        max_retries = 2

        for order in new_orders:
            order_id = order.get("id")
            order_code = order.get("attributes", {}).get("code")
            order_status = order.get("attributes", {}).get("status")

            # Валидация данных
            if not order_id or not order_code:
                logger.warning(f"Пропущен заказ без id/code: {order}")
                skipped.append(order)
                continue

            # Проверка статуса (например, уже принят)
            if order_status and order_status != "APPROVED_BY_BANK":
                # Пропуск невалидного заказа, не логируем
                skipped.append(order_id)
                continue

            # Попытки принять заказ
            attempt = 0
            accepted = False
            while attempt <= max_retries and not accepted:
                try:
                    result = await accept_order(order_id, order_code)
                    if result:
                        # Успешное принятие — не логируем подробно
                        success.append(order_id)
                        accepted = True
                    else:
                        attempt += 1
                        if attempt > max_retries:
                            logger.error(f"Не удалось принять заказ {order_id} ({order_code}) после {max_retries+1} попыток")
                            failed.append(order_id)
                except Exception as e:
                    attempt += 1
                    logger.error(f"Ошибка при принятии заказа {order_id} ({order_code}), попытка {attempt}: {e}")
                    if attempt > max_retries:
                        failed.append(order_id)

            processed += 1

        if failed:
            logger.warning(f"Не удалось принять заказы: {failed}")
        return {"processed": processed, "success": success, "failed": failed, "skipped": skipped}
    except Exception as e:
        logger.error(f"Error in process_new_orders: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return {"processed": 0, "success": [], "failed": [], "skipped": []}
    


async def process_single_order(order):
    try:
        order_id = order.get("id")
        order_code = order.get("attributes", {}).get("code")
        if await is_order_processed(order_id):
            return False

        products = await get_order_entries(order_id)
        stock_name = order.get("attributes", {}).get("pickupPointId")[-3:]
        attributes = order.get("attributes", {})
        customer_info = {
            "name": attributes.get("customer", {}).get("name"),
            "phone": attributes.get("customer", {}).get("cellPhone")
        }

        for entry in products:
            product_code = entry["attributes"]["offer"]["code"]
            order_quantity = entry["attributes"]["quantity"]
            current_quantity = await get_stock_quantity(product_code, stock_name)
            if current_quantity < order_quantity:
                logger.warning(f"Недостаточно товара {product_code} для заказа {order_code}: {current_quantity} < {order_quantity}")
                return False

        for entry in products:
            product_code = entry["attributes"]["offer"]["code"]
            order_quantity = entry["attributes"]["quantity"]
            current_quantity = await get_stock_quantity(product_code, stock_name)
            new_quantity = current_quantity - order_quantity
            await update_stock_quantity_and_log(product_code, new_quantity, order_quantity, "sales", stock_name)

        await save_order(order_id, order_code, order.get("attributes", {}).get("status"), stock_name, products, customer_info)
        invoice_result = await create_invoice(order_id)
        if invoice_result:
            return True
        else:
            logger.error(f"create_invoice вернул False для заказа {order_id}")
            return False
    except Exception as e:
        logger.error(f"Ошибка при обработке заказа {order.get('id')}: {e}")
        return False

async def process_orders():
    """Main order processing function (batch, limited concurrency)."""
    orders = await get_kaspi_delivery()
    if not orders:
        return {"processed": 0, "success": [], "failed": []}

    sem = asyncio.Semaphore(CONCURRENT_ORDER_LIMIT)
    success, failed = [], []

    async def sem_task(order):
        order_id = order.get("id")
        try:
            async with sem:
                result = await process_single_order(order)
                if result:
                    success.append(order_id)
                else:
                    failed.append(order_id)
        except Exception as e:
            failed.append(order_id)

    await asyncio.gather(*(sem_task(order) for order in orders))
    return {"processed": len(success), "success": success, "failed": failed}



async def save_waybill_links():
    """
    Для каждого заказа с waybill обновляет поле waybill у всех товаров заказа в kaspi_sold_products.
    """
    try:
        orders = await get_kaspi_delivery()
        if not orders:
            return []

        updated_ids = []
        for order in orders:
            order_id = order.get("id")
            waybill = order.get("attributes", {}).get("kaspiDelivery", {}).get("waybill")
            if not waybill:
                continue

            # Проверяем, что invoice_generated уже True (накладная реально создана)
            async with SessionLocalAsync() as session:
                result = await session.execute(
                    update(KaspiSoldProduct)
                    .where(KaspiSoldProduct.order_id == order_id)
                    .values(waybill=waybill)
                )
                # Проверяем invoice_generated
                from models import KaspiOrder
                invoice_row = await session.execute(
                    update(KaspiOrder)
                    .where(KaspiOrder.order_id == order_id)
                    .values(invoice_generated=True)
                    .returning(KaspiOrder.invoice_generated)
                )
                await session.commit()
                invoice_generated = invoice_row.scalar() if invoice_row else None
            if invoice_generated:
                updated_ids.append(order_id)
        return updated_ids
    except Exception as e:
        logger.error(f"Error in save_waybill_links: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return []



async def cancel_single_order(order):
    try:
        order_id = order.get("id")
        if not order_id:
            logger.warning("Пропущен заказ без id при отмене")
            return
        if not await is_order_processed(order_id):
            return
        if await is_order_canceled(order_id):
            return
        products = await get_order_products(order_id)
        if not products:
            logger.warning(f"Order {order_id} в архиве, но товары не найдены")
            return
        for product_code, quantity, product_name in products:
            await process_product_cancellation(product_code, quantity, order_id)
        await mark_order_as_canceled(order_id)
    except Exception as e:
        logger.error(f"Error canceling order {order.get('id')}: {e}")

async def cancel_orders_from_archive():
    """
    Находит все архивные заказы, которые не были обработаны и не отменены, и отменяет их (batch, limited concurrency).
    """
    try:
        archived_orders = await get_new_archive()
        if not archived_orders:
            return []
        sem = asyncio.Semaphore(CONCURRENT_ORDER_LIMIT)
        canceled_ids = []
        async def sem_task(order):
            async with sem:
                await cancel_single_order(order)
                order_id = order.get("id")
                if order_id:
                    canceled_ids.append(order_id)
        await asyncio.gather(*(sem_task(order) for order in archived_orders))
        return canceled_ids
    except Exception as e:
        logger.error(f"Error in cancel_orders_from_archive: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return []


async def cancel_orders_from_returned_archive():
    """
    Находит все архивные заказы со статусом RETURNED и применяет процедуру отмены без проверки повторной отмены.
    """
    try:
        returned_orders = await get_returned_archive()
        if not returned_orders:
            return []
        sem = asyncio.Semaphore(CONCURRENT_ORDER_LIMIT)
        canceled_ids = []

        async def sem_task(order):
            async with sem:
                await cancel_single_order(order)
                order_id = order.get("id")
                if order_id:
                    canceled_ids.append(order_id)

        await asyncio.gather(*(sem_task(order) for order in returned_orders))
        return canceled_ids
    except Exception as e:
        logger.error(f"Error in cancel_orders_from_returned_archive: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return []



async def log_event_to_db(session, level, message, extra_data=None):
    stmt = insert(LogEvent).values(
        level=level,
        message=message,
        extra_data=extra_data
    )
    await session.execute(stmt)
