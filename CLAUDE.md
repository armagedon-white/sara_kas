# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based asynchronous service for integrating with the Kaspi API (e-commerce platform in Kazakhstan). The service processes orders, manages inventory, handles cancellations, and generates shipping waybills. It runs as a background service designed for scheduled execution via GitHub Actions.

## Development Commands

### Setup and Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run the service locally
python main.py

# Run tests (when available)
pytest
```

### Environment Configuration
The service requires these environment variables:
- `DB_URL` - PostgreSQL connection URL
- `KASPI_API_URL` - Kaspi API endpoint
- `KASPI_AUTH_TOKEN` - Authentication token for Kaspi API
- `KASPI_CONTENT_TYPE` - HTTP content type header
- `KASPI_USER_AGENT` - User agent string for API requests

## Architecture Overview

### Core Components

**main.py:16** - Entry point that orchestrates the entire business process with retry logic
1. Cancels archived orders first (returns and regular cancellations)
2. Processes new orders with up to 5 retry attempts (10s delay between attempts)
3. Handles waybill generation for processed orders
4. Comprehensive error handling and logging throughout

**kaspi.py** - Kaspi API integration layer with:
- Async HTTP client using aiohttp
- Custom retry decorator with exponential backoff for network failures
- Time range calculations for date-based API queries
- Authentication handling (X-Auth-Token header)

**stock_service.py** - Business logic layer with:
- `process_new_orders()` - Retrieves and prepares new orders for processing
- `process_orders()` - Concurrent order processing (max 5 simultaneous tasks)
- `cancel_orders_from_archive()` - Handles order cancellations
- `save_waybill_links()` - Generates and stores shipping waybill URLs

**stock_repository.py** - Database operations layer:
- Async SQLAlchemy 2.0+ operations
- Retry mechanisms for database failures
- Inventory quantity management
- Order status tracking and updates

**models.py** - SQLAlchemy ORM models:
- `Product` - Product information and SKU management
- `Stock` - Warehouse/location management
- `StockInventory` - Product quantities by location
- `KaspiOrder` - Order information and status tracking
- `KaspiSoldProduct` - Individual order items
- `KaspiCanceledOrder` - Cancellation tracking
- `LogEvent` - Application event logging

**db_conn.py** - Database configuration:
- Async SQLAlchemy engine setup with asyncpg driver
- Session factory configuration for async operations
- Environment variable loading via python-dotenv

**logger_conf.py** - Centralized logging configuration with database handler

### Key Business Flow

1. **Cancellation Processing**: Service first processes returned and archived cancellations to maintain inventory accuracy
2. **New Order Retrieval**: Fetches unprocessed orders from Kaspi API within calculated time windows
3. **Order Processing**: Concurrently processes up to 5 orders, updating inventory and order statuses
4. **Retry Logic**: Failed operations are retried up to 5 times with 10-second delays
5. **Waybill Generation**: Creates shipping documents for successfully processed orders
6. **Early Termination**: If orders are cancelled during processing, subsequent attempts are stopped

### Concurrency and Performance

- **Async/Await**: Full async stack for high performance I/O operations
- **Concurrent Processing**: Maximum 5 orders processed simultaneously via `asyncio.gather()`
- **Database Pooling**: SQLAlchemy connection pooling for efficient database usage
- **Retry Mechanisms**: Both API and database operations have built-in retry with exponential backoff

### Error Handling and Resilience

- **Network Resilience**: API calls have retry logic with exponential backoff
- **Database Resilience**: Database operations include retry mechanisms
- **Order Cancellation Detection**: Service checks for cancellations between retry attempts
- **Comprehensive Logging**: All operations logged to both console and database
- **Graceful Degradation**: Failed operations don't crash the entire service

## Deployment and Operations

### GitHub Actions
- **Scheduled Execution**: Runs every 30 minutes via cron (`0,30 * * * *`)
- **Manual Trigger**: Can be triggered manually via `workflow_dispatch`
- **Python 3.11** runtime with pip caching for performance
- **Environment Variables**: All secrets stored in GitHub repository secrets

### Production Considerations
- Service is designed for stateless operation suitable for containerization
- Database connections are properly managed with connection pooling
- All external API calls include proper timeout handling
- Logging includes timing information for performance monitoring

## Database Schema

The service uses PostgreSQL with the following key tables:
- **products** - Product catalog with SKU mappings
- **stocks** - Warehouse/location definitions
- **stock_inventory** - Current inventory levels by location
- **kaspi_orders** - Order tracking with status management
- **kaspi_sold_products** - Line items within orders
- **kaspi_canceled_orders** - Cancellation tracking and reasons
- **log_events** - Application audit trail

Key indexes exist on order_id, product_code, and status fields for performance.