import os
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker,Session
from contextlib import contextmanager

AGENT_MODE=os.getenv("AGENT_MODE","testdata")
DB_NAME="testdata.db" if AGENT_MODE=="testdata" else"production.db"
DATA_DIR=os.path.join(os.path.dirname(os.path.dirname(__file__)),"data")
os.makedirs(DATA_DIR,exist_ok=True)
DATABASE_URL=f"sqlite:///{os.path.join(DATA_DIR,DB_NAME)}"

engine=create_engine(
 DATABASE_URL,
 echo=False,
 connect_args={"check_same_thread":False,"timeout":30},
 pool_pre_ping=True,
)


@event.listens_for(engine,"connect")
def set_sqlite_pragma(dbapi_connection,connection_record):
 cursor=dbapi_connection.cursor()
 cursor.execute("PRAGMA journal_mode=WAL")
 cursor.execute("PRAGMA busy_timeout=30000")
 cursor.execute("PRAGMA synchronous=NORMAL")
 cursor.close()
SessionLocal=sessionmaker(bind=engine,autocommit=False,autoflush=False)

def get_session()->Session:
 return SessionLocal()

@contextmanager
def session_scope():
 session=SessionLocal()
 try:
  yield session
  session.commit()
 except Exception:
  session.rollback()
  raise
 finally:
  session.close()

def init_db():
 from .tables import Base
 Base.metadata.create_all(bind=engine)
