import aiohttp
import asyncio
import functools
from datetime import datetime, timedelta, timezone
from logger_conf import logger
from dotenv import load_dotenv
import os

load_dotenv()

KASPI_API_URL = os.getenv("KASPI_API_URL")
KASPI_HEADERS = {
    "Content-Type": os.getenv("KASPI_CONTENT_TYPE"),
    "X-Auth-Token": os.getenv("KASPI_AUTH_TOKEN"),
    "User-Agent": os.getenv("KASPI_USER_AGENT")
}


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


async def get_utc_day_range():
    try:
        now_utc = datetime.now(timezone.utc)
        start_of_yesterday = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc) - timedelta(days=1)
        end_of_today = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)

        return str(int(start_of_yesterday.timestamp() * 1000)), str(int(end_of_today.timestamp() * 1000))
    except Exception as e:
        logger.error(f"Error getting UTC timestamps: {e}")
        return None, None


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_new_orders():
    """Gets new orders from Kaspi API."""
    try:
        start_timestamp, end_timestamp = await get_utc_day_range()
        params = {
            "page[number]": 0,
            "page[size]": 100,
            "filter[orders][state]": "NEW",
            "filter[orders][creationDate][$ge]": str(start_timestamp),
            "filter[orders][creationDate][$le]": str(end_timestamp),
            "filter[orders][status]": "APPROVED_BY_BANK"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(KASPI_API_URL, headers=KASPI_HEADERS, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    # logger.info(f"Retrieved {len(data.get('data', []))} new orders")
                    return data.get("data", [])
                return []
    except Exception as e:
        logger.error(f"Ошибка при получении новых заказов: {e}")
        return []


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_kaspi_delivery():
    try:
        start_timestamp, end_timestamp = await get_utc_day_range()
        params = {
            "page[number]": 0,
            "page[size]": 20,
            "filter[orders][state]": "KASPI_DELIVERY",
            "filter[orders][creationDate][$ge]": str(start_timestamp),
            "filter[orders][creationDate][$le]": str(end_timestamp),
            "filter[orders][status]": "ACCEPTED_BY_MERCHANT"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(KASPI_API_URL, headers=KASPI_HEADERS, params=params) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    return data.get("data", [])
                return []
    except Exception as e:
        logger.error(f"Ошибка при получении delivery-заказов: {e}")
        return []


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_new_archive():
    try:
        start_timestamp, end_timestamp = await get_utc_day_range()
        params = {
            "page[number]": 0,
            "page[size]": 50,  # Уменьшаем размер страницы для оптимизации
            "filter[orders][state]": "ARCHIVE",
            "filter[orders][creationDate][$ge]": str(start_timestamp),
            "filter[orders][creationDate][$le]": str(end_timestamp),
            "filter[orders][status]": "CANCELLED"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(KASPI_API_URL, headers=KASPI_HEADERS, params=params) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    return data.get("data", [])
                logger.warning(f"Kaspi API вернул ошибку: {response.status}")
                return []
    except Exception as e:
        logger.error(f"Ошибка при получении архива заказов: {e}")
        return []


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_returned_archive():
    try:
        start_timestamp, end_timestamp = await get_utc_day_range()
        params = {
            "page[number]": 0,
            "page[size]": 50,
            "filter[orders][state]": "ARCHIVE",
            "filter[orders][creationDate][$ge]": str(start_timestamp),
            "filter[orders][creationDate][$le]": str(end_timestamp),
            "filter[orders][status]": "RETURNED"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(KASPI_API_URL, headers=KASPI_HEADERS, params=params) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    return data.get("data", [])
                logger.warning(f"Kaspi API вернул ошибку при получении возвратов: {response.status}")
                return []
    except Exception as e:
        logger.error(f"Ошибка при получении архива возвратов: {e}")
        return []


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def get_order_entries(order_id):
    try:
        entries_url = f"https://kaspi.kz/shop/api/v2/orders/{order_id}/entries"
        async with aiohttp.ClientSession() as session:
            async with session.get(entries_url, headers=KASPI_HEADERS) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    return data.get("data", [])
                return []
    except Exception as e:
        logger.error(f"Ошибка при получении позиций заказа: {e}")
        return []


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def accept_order(order_id, order_code):
    try:
        payload = {
            "data": {
                "type": "orders",
                "id": order_id,
                "attributes": {"code": order_code, "status": "ACCEPTED_BY_MERCHANT"}
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(KASPI_API_URL, headers=KASPI_HEADERS, json=payload) as response:
                if response.status in [200, 201]:
                    return True
                logger.warning(f"Ошибка при принятии заказа {order_id}: {await response.text()}")
                return False
    except Exception as e:
        logger.error(f"Ошибка в accept_order: {e}")
        return False


@async_retry(retries=3, backoff_in_seconds=2, allowed_exceptions=(aiohttp.ClientError, asyncio.TimeoutError))
async def create_invoice(order_id, number_of_space=1):
    try:
        payload = {
            "data": {
                "type": "orders",
                "id": order_id,
                "attributes": {
                    "status": "ASSEMBLE",
                    "numberOfSpace": str(number_of_space)
                }
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(KASPI_API_URL, headers=KASPI_HEADERS, json=payload) as response:
                if response.status in [200, 201]:
                    return True
                logger.warning(f"Ошибка при создании накладной для {order_id}: {await response.text()}")
                return False
    except Exception as e:
        logger.error(f"Ошибка в create_invoice: {e}")
        return False
