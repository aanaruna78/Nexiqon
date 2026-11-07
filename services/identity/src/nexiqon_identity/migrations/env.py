from nexiqon_core.migrations import run_env
from nexiqon_identity.models import Base

run_env(Base.metadata)
