from nexiqon_core.migrations import run_env
from nexiqon_model_gateway.models import Base

run_env(Base.metadata)
