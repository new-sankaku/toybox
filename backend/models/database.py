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

def _get_schema_version(conn,text_func):
 try:
  result=conn.execute(text_func("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"))
  row=result.fetchone()
  return row[0] if row else 0
 except Exception:
  return 0

def _set_schema_version(conn,text_func,version):
 conn.execute(text_func("INSERT INTO schema_version (version, applied_at) VALUES (:v, CURRENT_TIMESTAMP)"),{"v":version})

MIGRATIONS=[
 (1,"llm_jobs","system_prompt","ALTER TABLE llm_jobs ADD COLUMN system_prompt TEXT"),
 (2,"llm_jobs","temperature","ALTER TABLE llm_jobs ADD COLUMN temperature VARCHAR(10)"),
 (3,"llm_jobs","messages_json","ALTER TABLE llm_jobs ADD COLUMN messages_json TEXT"),
 (4,"agent_traces","output_summary","ALTER TABLE agent_traces ADD COLUMN output_summary TEXT"),
 (5,"api_key_store","latency_ms","ALTER TABLE api_key_store ADD COLUMN latency_ms INTEGER"),
 (6,"assets","agent_id","ALTER TABLE assets ADD COLUMN agent_id VARCHAR(50)"),
 (7,"llm_jobs","tools_json","ALTER TABLE llm_jobs ADD COLUMN tools_json TEXT"),
]

def _run_migrations():
 from sqlalchemy import inspect,text
 from middleware.logger import get_logger
 logger=get_logger()
 inspector=inspect(engine)
 table_names=set(inspector.get_table_names())
 if"schema_version" not in table_names:
  with engine.begin() as conn:
   conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
 with engine.begin() as conn:
  current_version=_get_schema_version(conn,text)
  applied=0
  for version,table,column,sql in MIGRATIONS:
   if version<=current_version:
    continue
   if table not in table_names:
    _set_schema_version(conn,text,version)
    continue
   columns={c["name"] for c in inspector.get_columns(table)}
   if column not in columns:
    conn.execute(text(sql))
    logger.info(f"Migration v{version}: Added {column} to {table}")
   _set_schema_version(conn,text,version)
   applied+=1
  if applied>0:
   logger.info(f"Applied {applied} migration(s), current version: {version}")

def init_db():
 from .tables import Base
 Base.metadata.create_all(bind=engine)
 _run_migrations()
