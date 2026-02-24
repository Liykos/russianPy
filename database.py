# database.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import os

# 加载 .env 文件中的 DATABASE_URL
load_dotenv()

# 使用您在 .env 文件中配置的 DATABASE_URL
# 例如: postgresql://srs_user:strong_password@localhost:54321/russian_srs_db
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_engine(DATABASE_URL)

# 创建会话 SessionLocal，用于每个请求的数据库操作
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 定义用于 FastAPI 依赖注入的生成器函数
def get_db():
    # 1. 创建数据库会话
    db: Session = SessionLocal()
    try:
        # 2. 将会话对象交给依赖注入系统
        yield db
    finally:
        # 3. 确保会话关闭
        db.close()