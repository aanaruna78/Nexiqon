from nexiqon_conversation.models import Base
from nexiqon_core.migrations import run_env

run_env(Base.metadata)
