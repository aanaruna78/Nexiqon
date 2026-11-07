from nexiqon_audit.models import Base
from nexiqon_core.migrations import run_env

run_env(Base.metadata)
