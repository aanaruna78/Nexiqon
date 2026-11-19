from nexiqon_core.migrations import run_env
from nexiqon_governance.models import Base

run_env(Base.metadata)
