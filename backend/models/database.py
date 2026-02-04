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

def _run_migrations():
 from sqlalchemy import inspect,text
 inspector=inspect(engine)
 if"llm_jobs" in inspector.get_table_names():
  columns={c["name"] for c in inspector.get_columns("llm_jobs")}
  if"system_prompt" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE llm_jobs ADD COLUMN system_prompt TEXT"))
  if"temperature" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE llm_jobs ADD COLUMN temperature VARCHAR(10)"))
  if"messages_json" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE llm_jobs ADD COLUMN messages_json TEXT"))
 if"agent_traces" in inspector.get_table_names():
  columns={c["name"] for c in inspector.get_columns("agent_traces")}
  if"output_summary" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE agent_traces ADD COLUMN output_summary TEXT"))
 if"api_key_store" in inspector.get_table_names():
  columns={c["name"] for c in inspector.get_columns("api_key_store")}
  if"latency_ms" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE api_key_store ADD COLUMN latency_ms INTEGER"))
 if"assets" in inspector.get_table_names():
  columns={c["name"] for c in inspector.get_columns("assets")}
  if"agent_id" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE assets ADD COLUMN agent_id VARCHAR(50)"))
 if"llm_jobs" in inspector.get_table_names():
  columns={c["name"] for c in inspector.get_columns("llm_jobs")}
  if"tools_json" not in columns:
   with engine.begin() as conn:
    conn.execute(text("ALTER TABLE llm_jobs ADD COLUMN tools_json TEXT"))

def init_db():
 from .tables import Base
 Base.metadata.create_all(bind=engine)
 _run_migrations()
