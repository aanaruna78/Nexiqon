from nexiqon_agent_runtime.models import Base
from nexiqon_core.migrations import run_env

run_env(Base.metadata)
