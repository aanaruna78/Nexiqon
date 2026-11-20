# Choose how to run Nexiqon

The product is the same in every option: the same Studio, assistants, security rules and APIs. What
changes is where it runs and who operates it.

| Option | Your data lives | Who runs it | Start here |
|---|---|---|---|
| **SaaS** | Nexiqon's cloud, in the region you choose | Nexiqon | [SaaS](saas.md) |
| **Hybrid** | Your Kubernetes cluster (documents, conversations, models) | You run the data plane; Nexiqon runs the control plane | [Hybrid](hybrid.md) |
| **Private (Kubernetes)** | Your cluster, in your cloud or data centre | You | [Private](private.md) |
| **One server** | One Linux server, optionally with GPUs | You | [Single node](single-node.md) |
| **Air-gapped** | A server or cluster with no internet access | You | [Air-gapped](air-gapped.md) |

**Models.** In every option, assistants use model **profiles**:

- cloud profiles (OpenAI, Anthropic, Gemini) work with your provider keys;
- on-premises profiles run open models on your GPUs with vLLM.

The data policy (**Models & data policy** in Studio) decides which data may reach which profile,
and it is enforced the same way everywhere.
