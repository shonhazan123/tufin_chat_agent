"""Seed the product-catalog SQLite database used by the database_query tool.

Creates ``data/catalog.db`` with ``products`` and ``orders`` tables populated
with fictional but realistic data.  Can be run standalone::

    python scripts/seed_catalog.py

or imported and called programmatically::

    from scripts.seed_catalog import seed_catalog_db
    seed_catalog_db("data/catalog.db")
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PRODUCTS_DDL = """\
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    price           REAL    NOT NULL,
    stock_quantity  INTEGER NOT NULL,
    description     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

ORDERS_DDL = """\
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    customer_name   TEXT    NOT NULL,
    quantity        INTEGER NOT NULL,
    total_price     REAL    NOT NULL,
    status          TEXT    NOT NULL,
    order_date      TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

_PRODUCTS = [
    (1,  "Wireless Bluetooth Headphones",  "Electronics",  79.99,  150, "Noise-cancelling over-ear headphones with 30h battery life",           "2025-11-01 09:00:00"),
    (2,  "USB-C Fast Charger",             "Electronics",  24.99,  300, "65W GaN charger with dual USB-C ports",                                "2025-11-05 10:30:00"),
    (3,  "Mechanical Keyboard",            "Electronics", 129.99,   85, "RGB hot-swappable mechanical keyboard with Cherry MX switches",        "2025-11-10 14:00:00"),
    (4,  "Running Shoes Pro",              "Sports",       89.99,  200, "Lightweight running shoes with carbon-fiber plate",                    "2025-11-15 08:00:00"),
    (5,  "Yoga Mat Premium",               "Sports",       34.99,  400, "6mm thick non-slip yoga mat with carrying strap",                     "2025-11-20 11:00:00"),
    (6,  "Resistance Bands Set",           "Sports",       19.99,  500, "Set of 5 latex resistance bands with varying tensions",               "2025-12-01 09:15:00"),
    (7,  "Cotton T-Shirt Classic",         "Clothing",     14.99,  600, "100% organic cotton crew-neck t-shirt",                               "2025-12-05 10:00:00"),
    (8,  "Winter Jacket Waterproof",       "Clothing",    149.99,   75, "Insulated waterproof jacket rated to -20C",                           "2025-12-10 13:00:00"),
    (9,  "Slim Fit Jeans",                 "Clothing",     49.99,  250, "Stretch denim slim-fit jeans",                                        "2025-12-15 14:30:00"),
    (10, "Smart LED Desk Lamp",            "Home",         39.99,  180, "Adjustable LED lamp with wireless phone charging base",               "2025-12-20 09:00:00"),
    (11, "Stainless Steel Water Bottle",   "Home",         22.99,  350, "750ml double-wall vacuum insulated water bottle",                     "2026-01-02 10:00:00"),
    (12, "Cast Iron Skillet 12-inch",      "Home",         44.99,  120, "Pre-seasoned cast iron skillet suitable for all cooktops",             "2026-01-05 11:30:00"),
    (13, "The Art of Programming",         "Books",        39.99,   90, "Comprehensive guide to software engineering best practices",           "2026-01-10 08:00:00"),
    (14, "Data Science Handbook",          "Books",        34.99,  110, "Practical data science with Python examples",                          "2026-01-15 09:30:00"),
    (15, "Sci-Fi Novel Collection",        "Books",        27.99,  200, "Box set of 5 award-winning science fiction novels",                    "2026-01-20 10:45:00"),
    (16, "4K Webcam",                      "Electronics",  59.99,  160, "4K autofocus webcam with built-in ring light and microphone",          "2026-02-01 12:00:00"),
    (17, "Hiking Backpack 40L",            "Sports",       64.99,  130, "Waterproof 40-liter hiking backpack with rain cover",                  "2026-02-05 08:30:00"),
    (18, "Wool Beanie Hat",                "Clothing",     12.99,  450, "Merino wool knit beanie for cold weather",                             "2026-02-10 09:00:00"),
    (19, "Ceramic Plant Pot Set",          "Home",         29.99,  220, "Set of 3 minimalist ceramic pots with drainage holes",                 "2026-02-15 11:00:00"),
    (20, "Mystery Thriller Bestseller",    "Books",        16.99,  300, "Page-turning mystery thriller — 2026 bestseller",                      "2026-02-20 14:00:00"),
]

_ORDERS = [
    (1,   1,  "Alice Johnson",    1,   79.99, "delivered",  "2026-01-10 14:22:00"),
    (2,   3,  "Bob Smith",        1,  129.99, "delivered",  "2026-01-11 09:05:00"),
    (3,   7,  "Charlie Davis",    3,   44.97, "delivered",  "2026-01-12 16:30:00"),
    (4,   5,  "Diana Martinez",   2,   69.98, "delivered",  "2026-01-14 11:15:00"),
    (5,   2,  "Ethan Brown",      2,   49.98, "delivered",  "2026-01-15 08:45:00"),
    (6,  10,  "Fiona Wilson",     1,   39.99, "delivered",  "2026-01-18 13:00:00"),
    (7,  13,  "George Lee",       1,   39.99, "delivered",  "2026-01-20 10:30:00"),
    (8,   4,  "Hannah Clark",     1,   89.99, "shipped",   "2026-02-01 09:00:00"),
    (9,   8,  "Ivan Patel",       1,  149.99, "shipped",   "2026-02-03 14:20:00"),
    (10, 15,  "Julia Kim",        2,   55.98, "shipped",   "2026-02-05 11:45:00"),
    (11,  6,  "Alice Johnson",    1,   19.99, "shipped",   "2026-02-07 16:10:00"),
    (12, 11,  "Bob Smith",        3,   68.97, "shipped",   "2026-02-08 08:30:00"),
    (13, 16,  "Charlie Davis",    1,   59.99, "pending",   "2026-02-20 10:00:00"),
    (14, 12,  "Diana Martinez",   1,   44.99, "pending",   "2026-02-21 12:30:00"),
    (15,  9,  "Ethan Brown",      2,   99.98, "pending",   "2026-02-22 15:00:00"),
    (16, 14,  "Fiona Wilson",     1,   34.99, "pending",   "2026-02-23 09:45:00"),
    (17, 17,  "George Lee",       1,   64.99, "pending",   "2026-02-24 14:00:00"),
    (18, 19,  "Hannah Clark",     2,   59.98, "pending",   "2026-02-25 11:20:00"),
    (19, 20,  "Ivan Patel",       1,   16.99, "cancelled", "2026-02-10 08:00:00"),
    (20,  7,  "Julia Kim",        5,   74.95, "cancelled", "2026-02-12 13:30:00"),
    (21,  1,  "Alice Johnson",    2,  159.98, "delivered",  "2026-02-15 10:15:00"),
    (22,  3,  "Charlie Davis",    1,  129.99, "delivered",  "2026-02-16 09:00:00"),
    (23,  2,  "Ethan Brown",      1,   24.99, "delivered",  "2026-02-18 14:45:00"),
    (24,  5,  "Diana Martinez",   1,   34.99, "shipped",   "2026-03-01 08:30:00"),
    (25, 10,  "Bob Smith",        2,   79.98, "shipped",   "2026-03-02 11:00:00"),
    (26, 18,  "Fiona Wilson",     3,   38.97, "shipped",   "2026-03-03 16:20:00"),
    (27,  4,  "George Lee",       1,   89.99, "pending",   "2026-03-05 09:15:00"),
    (28, 16,  "Hannah Clark",     1,   59.99, "pending",   "2026-03-06 12:00:00"),
    (29, 11,  "Ivan Patel",       1,   22.99, "pending",   "2026-03-07 14:30:00"),
    (30, 13,  "Julia Kim",        1,   39.99, "pending",   "2026-03-08 10:45:00"),
    (31,  8,  "Alice Johnson",    1,  149.99, "delivered",  "2026-03-10 08:00:00"),
    (32,  6,  "Bob Smith",        2,   39.98, "delivered",  "2026-03-11 09:30:00"),
    (33, 15,  "Charlie Davis",    1,   27.99, "shipped",   "2026-03-12 11:15:00"),
    (34,  9,  "Diana Martinez",   1,   49.99, "shipped",   "2026-03-13 13:00:00"),
    (35, 12,  "Ethan Brown",      2,   89.98, "shipped",   "2026-03-14 15:45:00"),
    (36, 14,  "Fiona Wilson",     1,   34.99, "pending",   "2026-03-15 08:20:00"),
    (37, 20,  "George Lee",       3,   50.97, "pending",   "2026-03-16 10:00:00"),
    (38, 17,  "Hannah Clark",     1,   64.99, "pending",   "2026-03-17 12:30:00"),
    (39,  1,  "Ivan Patel",       1,   79.99, "pending",   "2026-03-18 14:00:00"),
    (40,  3,  "Julia Kim",        1,  129.99, "pending",   "2026-03-19 16:15:00"),
]


def seed_catalog_db(db_path: str | Path) -> None:
    """Create (or recreate) the catalog database with sample data."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if db_path.exists():
            db_path.unlink()
    except PermissionError:
        pass

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        conn.execute("DROP TABLE IF EXISTS orders")
        conn.execute("DROP TABLE IF EXISTS products")
        conn.execute(PRODUCTS_DDL)
        conn.execute(ORDERS_DDL)

        conn.executemany(
            "INSERT INTO products (id, name, category, price, stock_quantity, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _PRODUCTS,
        )
        conn.executemany(
            "INSERT INTO orders (id, product_id, customer_name, quantity, total_price, status, order_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _ORDERS,
        )

        conn.commit()
        print(f"Seeded {len(_PRODUCTS)} products and {len(_ORDERS)} orders into {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/catalog.db")
    seed_catalog_db(target)
