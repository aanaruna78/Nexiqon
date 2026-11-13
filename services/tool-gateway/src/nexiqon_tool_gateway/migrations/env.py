from nexiqon_core.migrations import run_env
from nexiqon_tool_gateway.models import Base

run_env(Base.metadata)
