from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from dotenv import load_dotenv
import os

load_dotenv()

# Use a single environment variable for the full DB URL
DATABASE_URL_ASYNC = os.getenv("DB_URL")


# ---------- АСИНХРОННОЕ подключение ----------
engine_async = create_async_engine(
    DATABASE_URL_ASYNC,
    echo=False,
)

SessionLocalAsync = async_sessionmaker(
    bind=engine_async,
    expire_on_commit=False,
)
