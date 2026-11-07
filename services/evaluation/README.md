# evaluation

Test sets, evaluation runs, scorecards and release gates. Plane: **control**.

Generated from `templates/service`; see `docs/plan/ARCHITECTURE.md` for this service's responsibilities.

* App factory: `nexiqon_evaluation.main:create_app`
* Served under `/evaluation` (grouped or split, see `deploy/groups.yaml`)
* Tenant lifecycle hooks: `nexiqon_evaluation/lifecycle.py` (replace the stub once the service stores tenant data)

```bash
uv run pytest services/evaluation
uv run nexiqon-run --services evaluation
```
