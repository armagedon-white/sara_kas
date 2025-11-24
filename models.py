from sqlalchemy import Float, ForeignKey, TIMESTAMP, DECIMAL, func, JSON
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, Index

Base = declarative_base()


class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(255), unique=True, index=True)
    model = Column(String(255), nullable=False)
    brand = Column(String(15), nullable=False)
    price = Column(Float, nullable=False)
    preorder = Column(Integer, default=0, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    stock_inventory = relationship("StockInventory", back_populates="product")

    def __repr__(self):
        return f"<Product(model='{self.model}', price={self.price})>"


class Stock(Base):
    __tablename__ = 'stocks'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    stock_inventory = relationship("StockInventory", back_populates="stock")

    def __repr__(self):
        return f"<Stock(name='{self.name}')>"


class StockInventory(Base):
    __tablename__ = 'stock_inventory'
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey('products.id'), nullable=False)
    stock_id = Column(Integer, ForeignKey('stocks.id'), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    product = relationship("Product", back_populates="stock_inventory")
    stock = relationship("Stock", back_populates="stock_inventory")

    def __repr__(self):
        return f"<StockInventory(product_id='{self.product_id}', stock_id='{self.stock_id}', quantity={self.quantity})>"


class KaspiOrder(Base):
    __tablename__ = 'kaspi_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), nullable=False, unique=True, index=True)
    order_code = Column(String(100), nullable=False, index=True)
    stock_name = Column(String(100), nullable=False)
    status = Column(String(100), nullable=False)
    invoice_generated = Column(Boolean, default=False)
    is_returned = Column(Boolean, default=False)
    is_canceled = Column(Boolean, default=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    sold_products = relationship("KaspiSoldProduct", back_populates="order", cascade="all, delete-orphan")


class KaspiSoldProduct(Base):
    __tablename__ = 'kaspi_sold_products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), ForeignKey('kaspi_orders.order_id', ondelete='CASCADE', onupdate='CASCADE'),
                      nullable=False, index=True)
    order_code = Column(String(100), nullable=False, index=True)
    product_code = Column(String(100), nullable=False, index=True)
    product_name = Column(String(255), nullable=True)
    quantity = Column(Integer, nullable=False)
    price = Column(DECIMAL(10, 2), nullable=False)
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(32), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)
    waybill = Column(String(512), nullable=True)
    order = relationship("KaspiOrder", back_populates="sold_products")


class KaspiCanceledOrder(Base):
    __tablename__ = 'kaspi_canceled_orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(100), nullable=False, index=True)
    order_code = Column(String(100), nullable=False, index=True)
    product_code = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now(), nullable=False)




class LogEvent(Base):
    __tablename__ = 'log_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    level = Column(String(32), nullable=False, default='INFO')
    message = Column(String, nullable=False)
    extra_data = Column(JSON, nullable=True)


