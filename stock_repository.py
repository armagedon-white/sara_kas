from sqlalchemy import select, exists, text
from sqlalchemy.exc import SQLAlchemyError
from db_conn import SessionLocalAsync
from logger_conf import logger
from models import KaspiOrder, KaspiSoldProduct, Product, StockInventory, Stock, KaspiCanceledOrder
import os
from datetime import datetime
import asyncio
import functools


def async_retry(retries=3, backoff_in_seconds=1, allowed_exceptions=(Exception,)):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            attempt = 0
            delay = backoff_in_seconds
            while True:
                try:
                    return await func(*args, **kwargs)
                except allowed_exceptions as e:
                    attempt += 1
                    if attempt > retries:
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2
        return wrapper
    return decorator


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(SQLAlchemyError, asyncio.TimeoutError))
async def get_product_id(product_code):
    """Получает product_id по коду товара асинхронно с использованием SQLAlchemy."""
    try:
        query = select(Product.id).where(Product.sku == product_code, Product.is_active == True)
        async with SessionLocalAsync() as session:
            result = await session.execute(query)
            product_id = result.scalar()
        if not product_id:
            logger.warning(f"Товар не найден по коду: {product_code}")
            return None
        return product_id
    except SQLAlchemyError as e:
        logger.error(f"Error getting product ID for code {product_code}: {e}")
        raise


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(SQLAlchemyError, asyncio.TimeoutError))
async def get_stock_quantity(product_code, stock_name="PP5", for_update=False):
    """Получает количество товара на складе асинхронно по названию склада."""
    try:
        query = (
            select(StockInventory.quantity)
            .join(Product, Product.id == StockInventory.product_id)
            .join(Stock, Stock.id == StockInventory.stock_id)
            .where(
                Product.sku == product_code,
                Stock.name == stock_name,
                StockInventory.is_active == True,
                Stock.is_active == True
            )
        )
        if for_update:
            query = query.with_for_update(skip_locked=False)
        async with SessionLocalAsync() as session:
            result = await session.execute(query)
            stock = result.first()
        quantity = stock[0] if stock and stock[0] is not None else 0
        return quantity
    except Exception as e:
        logger.error(f"Ошибка при получении остатков: {e}")
        return 0


# Обновляет количество товара на складе
@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(SQLAlchemyError, asyncio.TimeoutError))
async def update_stock_quantity_and_log(product_code, new_quantity, order_quantity, operation, stock_name):
    """Обновляет количество товара на складе."""
    async with SessionLocalAsync() as session:
            # Находим склад по названию
            stock_query = (
                select(Stock)
                .where(
                    Stock.name == stock_name,
                    Stock.is_active == True
                )
            )
            result = await session.execute(stock_query)
            stock = result.scalar_one_or_none()
            if not stock:
                logger.warning(f"Склад {stock_name} не найден или не активен!")
                return

            # Находим продукт
            product_query = (
                select(Product)
                .where(
                    Product.sku == product_code,
                    Product.is_active == True
                )
            )
            result = await session.execute(product_query)
            product = result.scalar_one_or_none()
            if not product:
                logger.warning(f"Товар {product_code} не найден или не активен!")
                return

            # Находим запись в StockInventory
            inventory_query = (
                select(StockInventory)
                .where(
                    StockInventory.product_id == product.id,
                    StockInventory.stock_id == stock.id,
                    StockInventory.is_active == True
                )
            )
            result = await session.execute(inventory_query)
            inventory = result.scalar_one_or_none()
            if not inventory:
                logger.warning(f"Нет записи о количестве товара {product_code} на складе {stock_name}")
                return

            if new_quantity < 0:
                logger.warning(f"0 или отрицательное количество товара для {product_code}")
                return

            # Обновляем количество
            inventory.quantity = new_quantity

            # ...логика журнала синхронизации удалена...




@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(SQLAlchemyError, asyncio.TimeoutError))
async def is_order_processed(order_id):
    """Проверяет, был ли заказ уже обработан."""
    try:
        async with SessionLocalAsync() as session:
            query = select(exists().where(KaspiOrder.order_id == order_id))

            result = await session.execute(query)
            exists_result = result.scalar()

            # Не логируем debug-информацию о статусе заказа

            return exists_result

    except Exception as e:
        logger.error(f"Ошибка при проверке статуса заказа {order_id}: {e}")
        return False


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(SQLAlchemyError, asyncio.TimeoutError))
async def save_order(order_id, order_code, status, stock_name, products, customer_info=None):
    """Сохраняет заказ и связанные товары в БД, используя SQLAlchemy."""
    try:
        new_order = KaspiOrder(
            order_id=order_id,
            order_code=order_code,
            status=status,
            stock_name=stock_name
        )
        async with SessionLocalAsync() as session:
            session.add(new_order)
            if products:
                customer_name = customer_info["name"] if customer_info else None
                customer_phone = customer_info["phone"] if customer_info else None
                product_objects = [
                    KaspiSoldProduct(
                        order_id=order_id,
                        order_code=order_code,
                        product_code=product["attributes"]["offer"]["code"],
                        product_name=product["attributes"]["offer"].get("name", ""),
                        quantity=product["attributes"].get("quantity", 0),
                        price=product["attributes"].get("totalPrice", 0),
                        customer_name=customer_name,
                        customer_phone=customer_phone
                    )
                    for product in products
                ]
                session.add_all(product_objects)
            await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при сохранении заказа {order_id}: {e}")
        raise


async def get_order_products(order_id: str):
    """Получает список товаров из заказа асинхронно."""
    try:
        async with SessionLocalAsync() as session:
            async with session.begin():
                # Выполняем запрос с использованием text для сырого SQL
                result = await session.execute(
                    text("SELECT product_code, quantity, product_name FROM kaspi_sold_products WHERE order_id = :order_id"),
                    {"order_id": order_id}
                )
                # Получаем все строки
                products = result.fetchall()
                return products
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении товаров заказа {order_id}: {e}")
        raise


async def save_canceled_order(order_id: str, product_code: str, session):
    """Сохраняет информацию об отменённом заказе асинхронно. Использует переданную сессию."""
    try:
        # Получаем order_code из kaspi_orders
        result = await session.execute(
            text("SELECT order_code FROM kaspi_orders WHERE order_id = :order_id"),
            {"order_id": order_id}
        )
        row = result.fetchone()
        order_code = row[0] if row else ""
        canceled_order = KaspiCanceledOrder(
            order_id=order_id,
            order_code=order_code,
            product_code=product_code
        )
        session.add(canceled_order)
        # Коммит не делаем здесь, чтобы вся операция была атомарной
    except Exception as e:
        logger.error(f"Ошибка при сохранении отменённого заказа {order_id}: {e}")
        raise


async def mark_order_as_canceled(order_id: str):
    """Отмечает заказ как отмененный в базе данных."""
    try:
        async with SessionLocalAsync() as session:
            await session.execute(
                text("UPDATE kaspi_orders SET is_canceled = TRUE WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при пометке заказа {order_id} как отменённого: {e}")
        raise

async def is_order_canceled(order_id: str) -> bool:
    """Проверяет, был ли заказ отменен."""
    try:
        async with SessionLocalAsync() as session:
            result = await session.execute(
                text("SELECT is_canceled FROM kaspi_orders WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            row = result.fetchone()
            return bool(row and row[0])
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при проверке отмены заказа {order_id}: {e}")
        return False


async def is_invoice_generated(order_id: str) -> bool:
    """Проверяет, была ли накладная уже сформирована для заказа."""
    try:
        async with SessionLocalAsync() as session:
            query = text("SELECT invoice_generated FROM kaspi_orders WHERE order_id = :order_id")
            result = await session.execute(query, {"order_id": order_id})
            row = result.fetchone()
            return bool(row[0]) if row else False
    except Exception as e:
        logger.error(f"Ошибка при проверке накладной для заказа {order_id}: {e}")
        return False

async def get_order_code(order_id: str) -> str:
    """Возвращает order_code для заказа."""
    try:
        async with SessionLocalAsync() as session:
            result = await session.execute(
                text("SELECT order_code FROM kaspi_orders WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            row = result.fetchone()
            return str(row[0]) if row else ""
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении кода заказа {order_id}: {e}")
        return ""


async def mark_order_as_invoiced(order_id: str):
    """Помечает заказ как обработанный."""
    try:
        async with SessionLocalAsync() as session:
            await session.execute(
                text("UPDATE kaspi_orders SET invoice_generated = TRUE WHERE order_id = :order_id"),
                {"order_id": order_id}
            )
            await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при пометке заказа {order_id} как обработанного: {e}")
        raise




async def process_product_cancellation(product_code, quantity, order_id):
    """Обрабатывает отмену товара и обновляет остатки на складе."""
    try:
        async with SessionLocalAsync() as session:
            await save_canceled_order(order_id, product_code, session)
            stock_name_query = text("""
                SELECT stock_name 
                FROM kaspi_orders ko
                JOIN kaspi_sold_products ksp ON ko.order_id = ksp.order_id
                WHERE ksp.product_code = :product_code 
                LIMIT 1
            """)
            stock_name_result = await session.execute(
                stock_name_query,
                {"product_code": product_code}
            )
            stock_name = stock_name_result.scalar_one_or_none()
            product_id = await get_product_id(product_code)
            if not product_id:
                logger.warning(f"Товар {product_code} не найден в БД")
                return
            is_canceled = await is_order_canceled(order_id)
            if is_canceled:
                return
            current_quantity = await get_stock_quantity(
                product_code,
                stock_name,
                for_update=True
            )
            new_quantity = current_quantity + quantity
            operation_type = 'return'
            await update_stock_quantity_and_log(
                product_code,
                new_quantity,
                quantity,
                operation=operation_type,
                stock_name=stock_name
            )
            await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при обработке отмены товара {product_code}: {e}")
        raise




