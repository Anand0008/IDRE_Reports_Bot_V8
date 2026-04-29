from __future__ import annotations
import os
from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from config.settings import get_settings

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = get_settings()
        ssl_args = {}
        ssl_path = os.path.abspath(s.db_ssl_ca)
        if os.path.exists(ssl_path):
            ssl_args = {"ssl_ca": ssl_path}

        url = (
            f"mysql+mysqlconnector://{s.db_user}:{s.db_password}"
            f"@{s.db_host}:{s.db_port}/{s.db_name}"
        )
        _engine = create_engine(
            url,
            connect_args=ssl_args,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


def test_connection() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Connection error: {e}")
        return False
