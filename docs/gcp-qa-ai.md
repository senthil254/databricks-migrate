# GCP Gen AI & Vertex AI — Interview Preparation Guide

> Consolidated coding questions, scenario questions, and answers for a **Gen AI / Vertex AI** role.
>
> **Target JD:** Gen AI (primary) · Vertex AI, Vertex AI Pipelines, Model Garden · Python (Flask/Django) · API design & OpenAPI · Docker/Kubernetes · Cloud infrastructure & DevOps.

---

## Table of Contents

**[Part 1 — GCP Gen AI Coding Questions](#part-1--gcp-gen-ai-coding-questions)**
1. [Call Gemini on Vertex AI](#11-call-gemini-on-vertex-ai-with-a-system-prompt-and-generation-config)
2. [RAG with Vertex AI embeddings](#12-build-a-rag-pipeline-with-vertex-ai-embeddings)
3. [Flask REST API wrapping Gemini](#13-flask-rest-api-wrapping-gemini-with-validation-and-error-handling)
4. [Retry with exponential backoff](#14-retry-with-exponential-backoff)
5. [OpenAPI spec](#15-openapi-spec-for-the-endpoint)
6. [Function calling (tools)](#16-function-calling-tools-with-gemini)
7. [Vertex AI Pipelines quick-start](#17-vertex-ai-pipelines-kfp-v2-quick-start)
8. [Model Garden deploy & fine-tuning](#18-deploy-a-model-garden-model-or-fine-tune-gemini)
9. [Dockerfile, Cloud Run & GKE](#19-dockerfile-and-cloud-run--gke-deployment)
10. [CI/CD with Cloud Build](#110-cicd-cloud-build)
11. [Unit-testing an LLM endpoint](#111-unit-test-an-llm-endpoint-by-mocking-the-model)
12. [Debugging quick reference](#112-debugging-scenario-questions)
13. [Conceptual Gen AI questions](#113-conceptual-gen-ai-questions)

**[Part 2 — Vertex AI Pipelines Deep Dive](#part-2--vertex-ai-pipelines-deep-dive)**
1. [Multi-output components](#21-lightweight-python-component-with-multiple-outputs)
2. [Artifacts: Input vs Output, path vs uri](#22-artifacts-input-vs-output-and-path-vs-uri)
3. [Full pipeline: compile & submit](#23-full-pipeline-with-parameters-compile--submit)
4. [Conditional deployment](#24-conditional-deployment-dslif--dslelif--dslelse)
5. [Fan-out / fan-in](#25-parallel-fan-out-with-parallelfor-and-fan-in-with-collected)
6. [Resources, GPUs, retries, caching](#26-control-resources-gpus-retries-timeouts-and-caching-per-task)
7. [How caching works](#27-caching-how-does-it-work-and-why-didnt-my-step-re-run)
8. [Custom container components](#28-custom-container-component-heavy-deps--private-code)
9. [Google Cloud Pipeline Components](#29-google-cloud-pipeline-components-gcpc)
10. [Reusing existing functions / YAML components](#210-convert-an-existing-function-into-a-component)
11. [Scheduling pipelines](#211-schedule-a-pipeline-recurring-runs)
12. [Secrets handling](#212-pass-secrets-without-hardcoding-credentials)
13. [Gen AI batch-eval pipeline](#213-gen-ai-pipeline-batch-evaluate-an-llm-with-gemini)
14. [Exit handlers](#214-exit-handler--cleanup-that-always-runs)
15. [Querying runs & lineage](#215-query-run-status-and-artifacts-programmatically)
16. [Testing pipelines before paying](#216-testing-a-pipeline-before-you-pay-for-a-run)
17. [Pipeline failure modes](#217-common-pipeline-failure-modes)
18. [Design: production LLM retraining pipeline](#218-design-a-production-llm-retraining-pipeline)

**[Part 3 — Scenario-Based Vertex AI Questions](#part-3--scenario-based-vertex-ai-questions)**
- [A. Model serving & scalability](#a-model-serving--scalability) · [B. Training & pipelines](#b-training--pipelines) · [C. Gen AI on Vertex](#c-gen-ai-on-vertex) · [D. Operations & troubleshooting](#d-operations--troubleshooting) · [E. Behavioural-technical](#e-behavioural-technical)

**[Part 4 — Cheat Sheets](#part-4--cheat-sheets)**

---
---

# Part 1 — GCP Gen AI Coding Questions

## 1.1 Call Gemini on Vertex AI with a system prompt and generation config

```python
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig

vertexai.init(project="my-proj", location="us-central1")

model = GenerativeModel(
    "gemini-1.5-pro",
    system_instruction="You are a concise banking assistant.",
)
resp = model.generate_content(
    "Explain RAG in 3 bullets",
    generation_config=GenerationConfig(
        temperature=0.2,
        max_output_tokens=512,
        top_p=0.9,
    ),
)
print(resp.text)
```

**Follow-ups to expect**

| Knob | What it does |
|---|---|
| `temperature` | Controls randomness. Low (0–0.2) for factual answers, higher for creative output. |
| `top_p` / `top_k` | Restrict the candidate token pool before sampling. |
| `safety_settings` | Per-category harm blocking thresholds. |
| `stream=True` | Returns an iterator of chunks — use it to cut perceived latency. |

---

## 1.2 Build a RAG pipeline with Vertex AI embeddings

```python
from vertexai.language_models import TextEmbeddingModel
import numpy as np

emb = TextEmbeddingModel.from_pretrained("text-embedding-004")
docs = ["Refunds take 5 days.", "Cards can be blocked via the app."]
doc_vecs = np.array([e.values for e in emb.get_embeddings(docs)])

def retrieve(query: str, k: int = 1):
    qv = np.array(emb.get_embeddings([query])[0].values)
    sims = doc_vecs @ qv / (np.linalg.norm(doc_vecs, axis=1) * np.linalg.norm(qv))
    return [docs[i] for i in sims.argsort()[::-1][:k]]

q = "How long for a refund?"
ctx = "\n".join(retrieve(q))
print(model.generate_content(f"Answer only from context:\n{ctx}\n\nQ: {q}").text)
```

**Follow-ups to expect**
- **Production vector store:** Vertex AI Vector Search (formerly Matching Engine), Vertex AI Search, or AlloyDB/Cloud SQL with `pgvector`.
- **Chunking:** ~500–1000 tokens with ~15% overlap, split on semantic boundaries.
- **Reranking:** re-order retrieved chunks by relevance before they hit the prompt.
- **Grounding:** attach answers to trusted sources to suppress hallucinations.

---

## 1.3 Flask REST API wrapping Gemini, with validation and error handling

```python
from flask import Flask, request, jsonify
from google.api_core import exceptions

app = Flask(__name__)

@app.post("/v1/generate")
def generate():
    body = request.get_json(silent=True) or {}
    prompt = body.get("prompt")
    if not prompt or len(prompt) > 8000:
        return jsonify(error="prompt required (<=8000 chars)"), 400
    try:
        r = model.generate_content(prompt)
        return jsonify(text=r.text, usage=r.usage_metadata.total_token_count)
    except exceptions.ResourceExhausted:
        return jsonify(error="rate limited"), 429
    except exceptions.GoogleAPICallError as e:
        return jsonify(error=str(e)), 502

@app.get("/healthz")
def health():
    return "ok"
```

**API best practices to mention:** path versioning (`/v1`), correct verbs & status codes, idempotency keys, pagination, OAuth/IAM or API Gateway auth, per-client rate limiting, and structured JSON logging with a request/trace ID.

---

## 1.4 Retry with exponential backoff

```python
import time, random
from google.api_core import exceptions

def with_retry(fn, retries: int = 5):
    for i in range(retries):
        try:
            return fn()
        except (exceptions.ResourceExhausted, exceptions.ServiceUnavailable):
            time.sleep((2 ** i) + random.random())   # exponential + jitter
    raise RuntimeError("max retries exceeded")
```

Production alternatives: `google.api_core.retry.Retry` or the `tenacity` library. Always add **jitter** — synchronised retries cause thundering herds.

---

## 1.5 OpenAPI spec for the endpoint

```yaml
openapi: 3.0.3
info:
  title: GenAI API
  version: 1.0.0
paths:
  /v1/generate:
    post:
      summary: Generate text from a prompt
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [prompt]
              properties:
                prompt:
                  type: string
                  maxLength: 8000
      responses:
        "200":
          description: OK
          content:
            application/json:
              schema:
                type: object
                properties:
                  text: { type: string }
        "400": { description: Bad request }
        "429": { description: Rate limited }
```

**Tip:** FastAPI emits OpenAPI automatically. For Flask use `flask-smorest` or `apispec`. Cloud Endpoints and API Gateway both consume an OpenAPI spec directly.

---

## 1.6 Function calling (tools) with Gemini

```python
from vertexai.generative_models import GenerativeModel, FunctionDeclaration, Tool, Part

get_rate = FunctionDeclaration(
    name="get_fx_rate",
    description="Get the FX rate for a currency pair",
    parameters={
        "type": "object",
        "properties": {"pair": {"type": "string"}},
        "required": ["pair"],
    },
)

chat = GenerativeModel("gemini-1.5-pro", tools=[Tool([get_rate])]).start_chat()
r = chat.send_message("USD to INR rate?")

call = r.candidates[0].content.parts[0].function_call
result = {"rate": 83.2}          # call the real API using call.args["pair"]

print(chat.send_message(
    Part.from_function_response(name=call.name, response=result)
).text)
```

---

## 1.7 Vertex AI Pipelines (KFP v2) quick-start

```python
from kfp import dsl, compiler
from google.cloud import aiplatform

@dsl.component(base_image="python:3.11", packages_to_install=["pandas"])
def preprocess(out: dsl.Output[dsl.Dataset]):
    import pandas as pd
    pd.DataFrame({"text": ["hi"]}).to_csv(out.path, index=False)

@dsl.component(base_image="python:3.11")
def evaluate(data: dsl.Input[dsl.Dataset]) -> float:
    return 0.92

@dsl.pipeline(name="genai-eval")
def pipe():
    p = preprocess()
    evaluate(data=p.outputs["out"])

compiler.Compiler().compile(pipe, "pipe.json")

aiplatform.PipelineJob(
    display_name="genai-eval",
    template_path="pipe.json",
    pipeline_root="gs://bucket/root",
).submit()
```

---

## 1.8 Deploy a Model Garden model or fine-tune Gemini

```python
# Supervised fine-tuning (SFT)
from vertexai.tuning import sft

job = sft.train(
    source_model="gemini-1.5-flash-002",
    train_dataset="gs://bucket/train.jsonl",
    epochs=3,
)

# Deploy an open model (Llama / Gemma) from Model Garden to an endpoint
from google.cloud import aiplatform
endpoint = aiplatform.Endpoint("projects/.../endpoints/123")
print(endpoint.predict(instances=[{"prompt": "Hello"}]).predictions)
```

**Know when to use each customisation approach**

| Approach | Use when |
|---|---|
| Prompt engineering | Always start here — zero cost, instant iteration. |
| RAG | The model needs **fresh or private facts**. |
| Fine-tuning (SFT) | You need a specific **style, format, or domain behaviour**. |
| LoRA / PEFT | Cheaper tuning — trains only small adapter weights. |

---

## 1.9 Dockerfile and Cloud Run / GKE deployment

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
CMD exec gunicorn -b :$PORT -w 2 app:app
```

```bash
gcloud run deploy genai-api --source . --region us-central1 \
  --service-account genai-sa@proj.iam.gserviceaccount.com \
  --no-allow-unauthenticated
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: genai-api
spec:
  replicas: 2
  selector:
    matchLabels: { app: genai-api }
  template:
    metadata:
      labels: { app: genai-api }
    spec:
      serviceAccountName: genai-ksa        # Workload Identity — no key files
      containers:
        - name: api
          image: us-docker.pkg.dev/proj/repo/genai-api:1.0
          ports: [{ containerPort: 8080 }]
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
          resources:
            requests: { cpu: "500m", memory: "512Mi" }
```

---

## 1.10 CI/CD (Cloud Build)

```yaml
steps:
  - name: python:3.11
    entrypoint: bash
    args: ["-c", "pip install -r requirements.txt pytest && pytest"]

  - name: gcr.io/cloud-builders/docker
    args: ["build", "-t", "us-docker.pkg.dev/$PROJECT_ID/repo/genai-api:$SHORT_SHA", "."]

  - name: gcr.io/cloud-builders/docker
    args: ["push", "us-docker.pkg.dev/$PROJECT_ID/repo/genai-api:$SHORT_SHA"]

  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args: ["gcloud", "run", "deploy", "genai-api",
           "--image", "us-docker.pkg.dev/$PROJECT_ID/repo/genai-api:$SHORT_SHA",
           "--region", "us-central1"]
```

---

## 1.11 Unit-test an LLM endpoint by mocking the model

```python
from unittest.mock import patch, MagicMock

def test_generate():
    fake = MagicMock(text="hi")
    fake.usage_metadata.total_token_count = 5
    with patch("app.model.generate_content", return_value=fake):
        c = app.test_client()
        assert c.post("/v1/generate", json={"prompt": "x"}).json["text"] == "hi"
        assert c.post("/v1/generate", json={}).status_code == 400
```

**Principle:** never call a real LLM in unit tests — it is slow, costly and non-deterministic. Keep live calls in a small, separately-tagged integration suite.

---

## 1.12 Debugging scenario questions

| Problem | Answer |
|---|---|
| `403 PERMISSION_DENIED` | Grant the SA `roles/aiplatform.user`; enable `aiplatform.googleapis.com`. |
| `429 ResourceExhausted` | Backoff + jitter, quota increase, global endpoint or Provisioned Throughput, batch requests. |
| Hallucinations | RAG/grounding, `temperature=0`, "answer only from context", run evals. |
| Response blocked or empty | Inspect `finish_reason` / `safety_ratings`; adjust `safety_settings`. |
| High latency | Stream, use Flash models, context caching, shorten prompts. |
| Output isn't valid JSON | `response_mime_type="application/json"` + `response_schema`. |
| High cost | Smaller models, context caching, batch prediction, cap `max_output_tokens`. |

---

## 1.13 Conceptual Gen AI questions

- **Transformer / attention** — the model weighs every token against every other token, which is what gives it long-range context.
- **Tokens & context window** — prompt + output must fit the limit; Gemini 1.5 supports ~1–2M tokens.
- **Embeddings** — text as dense vectors, compared with cosine similarity, enabling search by meaning.
- **Prompting techniques** — zero-shot, few-shot, chain-of-thought, ReAct.
- **Evaluation** — Vertex AI Gen AI Evaluation Service: groundedness, fluency, BLEU/ROUGE, LLM-as-judge.
- **Responsible AI** — safety filters, PII redaction via Cloud DLP, VPC-SC, CMEK, audit logs.
- **Agents** — Vertex AI Agent Builder, LangChain on Vertex AI, Agent Development Kit (ADK).

> **Interview tip:** structure every answer as **problem → GCP service choice → code → security (IAM/Workload Identity) → monitoring (Cloud Logging/Monitoring) → cost.**

---
---

# Part 2 — Vertex AI Pipelines Deep Dive

## 2.1 Lightweight Python component with multiple outputs

```python
from kfp import dsl
from typing import NamedTuple

@dsl.component(base_image="python:3.11", packages_to_install=["pandas==2.2.2"])
def split_stats(csv_uri: str) -> NamedTuple("Out", [("rows", int), ("ratio", float)]):
    import pandas as pd
    from collections import namedtuple
    df = pd.read_csv(csv_uri)
    Out = namedtuple("Out", ["rows", "ratio"])
    return Out(len(df), len(df[df.label == 1]) / len(df))
```

**Key points:** imports must be **inside** the function — the component runs standalone in its own container. Small values (`int`, `str`, `float`, `bool`, `list`, `dict`) are **parameters** stored in metadata; large data must travel as `Artifact`/`Dataset`.

---

## 2.2 Artifacts: Input vs Output, and `.path` vs `.uri`

```python
@dsl.component
def make_data(data: dsl.Output[dsl.Dataset]):
    data.metadata["source"] = "bq"
    with open(data.path, "w") as f:        # local FUSE path -> /gcs/bucket/...
        f.write("a,b\n1,2\n")

@dsl.component
def train(data: dsl.Input[dsl.Dataset], model: dsl.Output[dsl.Model]):
    print(data.uri)                        # gs://bucket/...
    rows = open(data.path).read()
    with open(model.path, "w") as f:
        f.write("weights")
    model.metadata["framework"] = "sklearn"
```

`.uri` is the `gs://` URI; `.path` is the Cloud Storage FUSE-mounted local path (`/gcs/...`) usable with ordinary file I/O. Artifacts are auto-tracked in **Vertex ML Metadata** for lineage.

---

## 2.3 Full pipeline with parameters, compile & submit

```python
from kfp import dsl, compiler
from google.cloud import aiplatform

@dsl.pipeline(name="churn-train", description="train + eval + conditional deploy")
def pipeline(project: str, bq_table: str, threshold: float = 0.85, epochs: int = 10):
    d = make_data()
    t = train(data=d.outputs["data"])

compiler.Compiler().compile(pipeline_func=pipeline, package_path="pipeline.yaml")

aiplatform.init(project="p", location="us-central1")
job = aiplatform.PipelineJob(
    display_name="churn-train",
    template_path="pipeline.yaml",
    pipeline_root="gs://my-bucket/pipeline-root",
    parameter_values={"project": "p", "bq_table": "ds.tbl", "threshold": 0.9},
    enable_caching=True,
)
job.submit(service_account="pipelines-sa@p.iam.gserviceaccount.com")
```

**Gotcha:** `job.run()` blocks, `job.submit()` is async. `pipeline_root` must be writable by the pipeline SA (`roles/storage.objectAdmin`).

---

## 2.4 Conditional deployment (`dsl.If` / `dsl.Elif` / `dsl.Else`)

```python
@dsl.pipeline(name="cond-deploy")
def pipeline(threshold: float = 0.85):
    tr = train()
    ev = evaluate(model=tr.outputs["model"])
    with dsl.If(ev.outputs["auc"] >= threshold, name="good-model"):
        deploy(model=tr.outputs["model"])
    with dsl.Else():
        notify(msg="model below threshold")
```

In KFP v2 this replaces v1's `dsl.Condition`. Conditions compare **parameters only**, never artifact contents — so return the metric as a `float` output.

---

## 2.5 Parallel fan-out with `ParallelFor` and fan-in with `Collected`

```python
from typing import List

@dsl.component
def tune(lr: float) -> float:
    return 1.0 - lr

@dsl.component
def pick_best(scores: dsl.Input[List[float]]) -> float:
    return max(scores)

@dsl.pipeline(name="hpt")
def pipeline():
    with dsl.ParallelFor([0.1, 0.01, 0.001], parallelism=3) as lr:
        t = tune(lr=lr)
    pick_best(scores=dsl.Collected(t.outputs["Output"]))
```

`parallelism` caps concurrent tasks; omit it for unbounded fan-out.

---

## 2.6 Control resources, GPUs, retries, timeouts and caching per task

```python
t = train(data=d.outputs["data"])
t.set_cpu_limit("8").set_memory_limit("32G")
t.set_accelerator_type("NVIDIA_TESLA_T4").set_accelerator_limit(1)
t.set_retry(num_retries=3, backoff_duration="60s", backoff_factor=2)
t.set_caching_options(False)          # force a re-run
t.set_env_variable("MLFLOW_URI", "http://x")
t.set_display_name("train-xgboost")
t.after(validate)                      # explicit ordering without a data dependency
```

---

## 2.7 Caching: how does it work, and why didn't my step re-run?

Vertex caches on a hash of **(component spec / image + input parameters + input artifact URIs)**. An identical hash in the same project+region replays the previous output and the step renders as *Cached*.

```python
PipelineJob(..., enable_caching=False)   # globally
task.set_caching_options(False)          # per task
```

**Classic trap:** mutable `:latest` image tags. The spec hash doesn't change, so stale code is silently reused. **Always pin image digests.**

---

## 2.8 Custom container component (heavy deps / private code)

```python
@dsl.container_component
def train_container(data: dsl.Input[dsl.Dataset], model: dsl.Output[dsl.Model], epochs: int):
    return dsl.ContainerSpec(
        image="us-docker.pkg.dev/proj/repo/trainer:1.0.3",
        command=["python", "train.py"],
        args=["--data", data.path, "--out", model.path, "--epochs", epochs],
    )
```

| Choose | When |
|---|---|
| `@dsl.component` | Quick Python steps, light deps. |
| `@dsl.container_component` | System packages, non-Python code, reproducible pinned image. |
| GCPC / `importer` | Managed Vertex operations with built-in polling and lineage. |

---

## 2.9 Google Cloud Pipeline Components (GCPC)

```python
from google_cloud_pipeline_components.v1.custom_job import CustomTrainingJobOp
from google_cloud_pipeline_components.v1.model import ModelUploadOp
from google_cloud_pipeline_components.v1.endpoint import EndpointCreateOp, ModelDeployOp

@dsl.pipeline(name="gcpc-train")
def pipeline(project: str, region: str):
    job = CustomTrainingJobOp(
        project=project, location=region, display_name="trainer",
        worker_pool_specs=[{
            "machine_spec": {"machine_type": "n1-standard-8"},
            "replica_count": 1,
            "container_spec": {"image_uri": "us-docker.pkg.dev/p/r/trainer:1.0"},
        }],
    )
    up = ModelUploadOp(project=project, location=region, display_name="m",
                       unmanaged_container_model=job.outputs["model"])
    ep = EndpointCreateOp(project=project, location=region, display_name="ep")
    ModelDeployOp(model=up.outputs["model"], endpoint=ep.outputs["endpoint"],
                  dedicated_resources_machine_type="n1-standard-4",
                  dedicated_resources_min_replica_count=1)
```

**Why GCPC:** these ops launch long-lived Vertex jobs (not inside the pipeline pod), handle polling/retries, and register lineage automatically.

---

## 2.10 Convert an existing function into a component

```python
from kfp import dsl, components

train_op = dsl.component(
    func=train_fn,
    base_image="python:3.11",
    packages_to_install=["scikit-learn"],
)

# Or load a reusable component definition
op = components.load_component_from_file("component.yaml")
# components.load_component_from_url("https://.../component.yaml")
```

---

## 2.11 Schedule a pipeline (recurring runs)

```python
schedule = job.create_schedule(
    display_name="nightly-retrain",
    cron="0 2 * * *",                       # UTC by default; "TZ=Asia/Kolkata 0 2 * * *"
    max_concurrent_run_count=1,
    max_run_count=365,
    service_account="pipelines-sa@p.iam.gserviceaccount.com",
)
```

**Alternatives:** Cloud Scheduler → Cloud Function → `PipelineJob.submit()`, or event-driven via Eventarc/Pub-Sub when new data lands in GCS.

---

## 2.12 Pass secrets without hardcoding credentials

```python
@dsl.component(packages_to_install=["google-cloud-secret-manager"])
def call_api(project: str, secret_id: str):
    from google.cloud import secretmanager
    c = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    key = c.access_secret_version(name=name).payload.data.decode()
```

**Never** pass secrets as pipeline parameters — parameter values are persisted in run metadata and visible in the console. The pipeline SA needs `roles/secretmanager.secretAccessor`.

---

## 2.13 Gen AI pipeline: batch-evaluate an LLM with Gemini

```python
@dsl.component(packages_to_install=["google-cloud-aiplatform"])
def batch_generate(prompts: dsl.Input[dsl.Dataset], out: dsl.Output[dsl.Dataset],
                   model_name: str = "gemini-2.0-flash"):
    import json, vertexai
    from vertexai.generative_models import GenerativeModel
    vertexai.init(location="us-central1")
    m = GenerativeModel(model_name)
    with open(prompts.path) as f, open(out.path, "w") as w:
        for line in f:
            p = json.loads(line)["prompt"]
            w.write(json.dumps({"prompt": p, "response": m.generate_content(p).text}) + "\n")

@dsl.component(packages_to_install=["google-cloud-aiplatform"])
def eval_metrics(preds: dsl.Input[dsl.Dataset], metrics: dsl.Output[dsl.Metrics]) -> float:
    score = 0.91                      # e.g. Gen AI Evaluation Service groundedness
    metrics.log_metric("groundedness", score)
    return score

@dsl.pipeline(name="llm-eval")
def pipeline(threshold: float = 0.85):
    g = batch_generate(prompts=load_prompts().outputs["out"])
    e = eval_metrics(preds=g.outputs["out"])
    with dsl.If(e.outputs["Output"] >= threshold):
        promote_prompt_version()
```

`dsl.Metrics` / `dsl.ClassificationMetrics` (`log_roc_curve`, `log_confusion_matrix`) render as charts in the Vertex console run view.

---

## 2.14 Exit handler / cleanup that always runs

```python
@dsl.component
def notify(status: str):
    print(f"pipeline finished: {status}")

@dsl.pipeline(name="with-exit")
def pipeline():
    exit_task = notify(status=dsl.PIPELINE_JOB_NAME_PLACEHOLDER)
    with dsl.ExitHandler(exit_task, name="cleanup"):
        train()
```

Useful placeholders: `PIPELINE_JOB_NAME_PLACEHOLDER`, `PIPELINE_JOB_ID_PLACEHOLDER`, `PIPELINE_TASK_NAME_PLACEHOLDER`, `PIPELINE_ROOT_PLACEHOLDER`. See also `dsl.IgnoreUpstreamFailure()`.

---

## 2.15 Query run status and artifacts programmatically

```python
from google.cloud import aiplatform

job = aiplatform.PipelineJob.get(
    "projects/p/locations/us-central1/pipelineJobs/churn-20250101"
)
print(job.state, job.has_failed)
for task in job.task_details:
    print(task.task_name, task.state, task.execution.metadata)

models = aiplatform.Artifact.list(filter='schema_title="system.Model"')
```

---

## 2.16 Testing a pipeline before you pay for a run

```python
import yaml
from kfp import compiler

def test_compiles(tmp_path):
    p = tmp_path / "p.yaml"
    compiler.Compiler().compile(pipeline, str(p))
    spec = yaml.safe_load(p.read_text())
    assert "train" in spec["root"]["dag"]["tasks"]

def test_component_logic():
    assert split_stats.python_func("data.csv").rows == 100
```

`component.python_func` unwraps the decorator for local unit testing. `kfp.local.init(runner=kfp.local.DockerRunner())` executes components locally. Always validate `compile()` in CI.

---

## 2.17 Common pipeline failure modes

| Symptom | Root cause / fix |
|---|---|
| `NameError: pd is not defined` | Import **inside** the component function. |
| `PermissionDenied` on `pipeline_root` | SA needs `roles/storage.objectAdmin` on the bucket, plus `roles/aiplatform.user` and `roles/iam.serviceAccountUser`. |
| Step shows *Cached* with stale results | Pin image digests; `enable_caching=False` / `set_caching_options(False)`. |
| `OOMKilled` / pod evicted | `set_memory_limit("32G")` or move to `CustomTrainingJobOp` on a bigger machine. |
| Artifact empty downstream | You wrote to a temp path instead of `artifact.path`. |
| `Component input type not supported` | Use supported parameter types or wrap large data in `Dataset`/`Artifact`. |
| Pipeline hangs on a GCPC op | The underlying Vertex job is still running — check Training/Batch Prediction, not pipeline logs. |
| Can't use `if` / `for` on an output | Outputs are compile-time placeholders — use `dsl.If` / `dsl.ParallelFor`. |
| Private PyPI deps fail | Use a custom container; `packages_to_install` only reaches public PyPI unless `pip_index_urls` is set. |

---

## 2.18 Design a production LLM retraining pipeline

1. **Trigger** — Cloud Scheduler cron, or Eventarc on new GCS/BigQuery data.
2. **Ingest & validate** — BigQuery extract → TFDV / Great Expectations schema check → fail fast via `dsl.If`.
3. **Prepare** — chunk & embed documents, write to Vertex AI Vector Search.
4. **Tune** — `sft.train()` on Gemini, or `CustomTrainingJobOp` for a custom model.
5. **Evaluate** — Gen AI Evaluation Service; log `dsl.Metrics`.
6. **Gate** — `dsl.If(new_score > champion_score)`; never auto-ship a regression.
7. **Register & deploy** — `ModelUploadOp` → `ModelDeployOp` with a canary traffic split.
8. **Monitor** — Vertex Model Monitoring for drift, Cloud Monitoring alerts, `ExitHandler` for Slack/Pub-Sub notification.
9. **Cross-cutting** — Workload Identity + dedicated SA, VPC-SC, CMEK, pinned digests, pipeline spec in Git, Cloud Build CI that compiles and integration-tests.

> **Interviewer-pleasing habits:** always mention *caching behaviour*, *parameters vs artifacts*, *which SA runs the pipeline*, and *when to push work out to a Vertex Custom Job instead of running it in the pipeline pod*.

---
---

# Part 3 — Scenario-Based Vertex AI Questions

*Answer format: **Situation → What you'd check → Solution → Trade-offs.** Interviewers score the diagnosis, not just the fix.*

## A. Model Serving & Scalability

### S1. "The endpoint is fine in testing, but at the 9 AM spike p99 latency jumps from 200 ms to 8 s with 503s."

**Diagnose first:** is it cold-start (scale-up lag) or saturation? Check `prediction/online/response_count`, replica count and CPU/GPU utilisation in Cloud Monitoring. Usually `min_replica_count=1`, and autoscaling needs 1–3 minutes to add replicas — so one pod absorbs the whole burst.

```python
endpoint.deploy(
    model=model,
    machine_type="n1-standard-8",
    min_replica_count=3,                       # warm floor sized to baseline QPS
    max_replica_count=20,
    autoscaling_target_cpu_utilization=60,     # scale earlier
    traffic_percentage=100,
)
```

- Load-test (Locust) to find QPS-per-replica, then set `min_replica = peak_QPS / QPS_per_replica`.
- Enable request-response logging to BigQuery to rule out payload bloat.
- For GPU models use `autoscaling_target_accelerator_duty_cycle` instead of CPU.
- For genuinely spiky traffic: client-side batching, or Pub/Sub queue + batch prediction.

**Trade-off:** a higher floor costs money 24×7. Alternative — a scheduled pre-warm job that scales up before the known spike and back down after.

---

### S2. "Finance says the Vertex AI bill tripled, and the endpoint is idle all night."

1. **Audit for forgotten endpoints.** Deployed models bill per node-hour **even at zero traffic** — this is the #1 real cause. `gcloud ai endpoints list --region=...` and undeploy orphans.
2. **Right-size.** If accelerator duty cycle is <20%, move to CPU with an optimised runtime (ONNX / optimised TF).
3. **Scale to zero** where supported, or undeploy overnight via Cloud Scheduler if the SLA allows.
4. **Online → batch.** If consumers only need daily scores, `BatchPredictionJob` is dramatically cheaper than a 24×7 endpoint.
5. **For LLMs:** Pro → Flash, enable context caching for repeated long prefixes, cap `max_output_tokens`, use batch prediction (~50% cheaper) offline.
6. **Pipelines:** enable caching, Spot/preemptible VMs for training, and set timeouts so runaway jobs die.
7. **Governance:** billing labels per team/model, budget alerts, BigQuery billing-export dashboard grouped by `resource.labels`.

---

### S3. "Deploy a new model version with zero downtime and prove it's safe."

```python
# Deploy v2 alongside v1 on the SAME endpoint and split traffic
endpoint.deploy(
    model=model_v2,
    deployed_model_display_name="v2",
    machine_type="n1-standard-4",
    min_replica_count=2,
    traffic_split={"<v1_id>": 90, "0": 10},    # "0" = the newly deployed model
)

# Promote once metrics look healthy
endpoint.update(traffic_split={"<v2_id>": 100})
# Rollback = flip the split back; v1 pods are still warm
```

Canary at 5–10% → watch latency, error rate **and prediction distribution** → ramp 10/25/50/100. Keep v1 deployed through the rollback window. Use shadow/mirror traffic first when no user impact is acceptable. Track versions in **Vertex AI Model Registry** with aliases (`default`, `champion`).

---

## B. Training & Pipelines

### S4. "A 3-hour training job OOMs at the 2h50m mark."

- **Immediate:** bigger memory (`n1-highmem-*`), smaller batch size, gradient accumulation, mixed precision, stream data instead of loading everything into pandas.
- **Structural:** checkpoint to GCS every N steps so restarts resume; enable `restart_job_on_worker_restart`.
- **Diagnostics:** Cloud Profiler / Vertex AI TensorBoard profiler to locate the spike — it's often **eval** time, where the batch is larger than train.
- **Prevention:** smoke-test on 1% of data in CI; split train and eval into separate pipeline components so the expensive step caches.

---

### S5. "A pipeline step silently used last week's data and shipped a stale model."

**Root cause: caching.** Vertex hashes component spec + input parameters + input artifact URIs. If the ingest component takes no parameters (it reads "today's" data internally), the hash never changes and the cached output replays forever.

**Fixes**
- Pass the partition date explicitly: `ingest(run_date=dsl.PIPELINE_JOB_SCHEDULE_TIME_UTC_PLACEHOLDER)`.
- `task.set_caching_options(False)` on non-deterministic/ingest steps.
- Pin images by **digest**, not `:latest`.
- Add a data-freshness assertion component that fails if `max(event_date) < today - 1`.

---

### S6. "Design an end-to-end MLOps setup on Vertex for a team of 6 shipping weekly."

| Layer | Choice |
|---|---|
| Source | Git — model code + pipeline definition, PR review |
| CI | Cloud Build: lint → unit tests → `Compiler().compile()` → build & push trainer image to Artifact Registry (immutable digest) |
| CD | Trigger `PipelineJob.submit()` in **dev**; promote to prod via separate project + approval |
| Orchestration | Vertex AI Pipelines; `create_schedule(cron="0 3 * * 1")` weekly |
| Data | BigQuery + **Vertex AI Feature Store** for train/serve consistency |
| Registry | Vertex AI Model Registry, version aliases, model card + eval metrics |
| Gate | `dsl.If(new_auc > champion_auc + 0.005)` |
| Serving | Endpoint with canary traffic split |
| Monitoring | Vertex Model Monitoring (skew/drift), Cloud Monitoring alerts, BigQuery request-response logs |
| Security | One SA per pipeline, Workload Identity, VPC-SC, CMEK, zero keys in code |
| Isolation | Separate projects: dev / staging / prod |

> **Line to say:** *"The pipeline definition is code in Git; nothing is clicked in the console. Every prod model is reproducible from a commit SHA plus a pipeline run ID."*

---

### S7. "Training works locally but the Vertex Custom Job can't read the GCS bucket."

1. **Which identity?** Custom jobs run as the **Vertex AI Custom Code Service Agent** unless you pass `service_account=`. Locally you used your own ADC — that's the discrepancy.
2. Grant that SA `roles/storage.objectViewer` on the input bucket and `objectAdmin` on the output path.
3. The caller needs `roles/iam.serviceAccountUser` on the SA to submit the job *as* it.
4. With VPC-SC, the bucket must sit inside the perimeter or have an ingress rule.
5. Check for region / CMEK key mismatch.
6. Smoke-test: `gsutil ls gs://bucket` in the container entrypoint before training starts.

---

## C. Gen AI on Vertex

### S8. "Our RAG chatbot gives confidently wrong answers about the refund policy."

**Diagnose in layers — don't jump to fine-tuning.**

1. **Retrieval or generation?** Log the retrieved chunks. ~70% of the time the right chunk was never retrieved.
2. **Retrieval fixes:** better chunking (500–800 tokens, ~15% overlap, semantic boundaries), hybrid search (BM25 + vector), a reranker, higher `top_k` then rerank down, metadata filters (product, locale, effective date).
3. **Stale index:** is the pipeline re-embedding updated policy docs? Add a scheduled re-index.
4. **Generation fixes:** `temperature=0`; system instruction *"Answer only from the provided context; if it is insufficient, say 'I don't know'"*; require inline citations to chunk IDs.
5. **Guardrails:** Vertex AI grounding with Vertex AI Search + a groundedness score from the Gen AI Evaluation Service; refuse below threshold.
6. **Measure:** a golden set of ~200 Q/A pairs run in a pipeline on every prompt/index change, gating on groundedness and answer-correctness.

> **Closing line:** *"Fine-tuning is the last resort here — it teaches style, not facts. Facts belong in retrieval."*

---

### S9. "Gemini calls intermittently fail with 429 ResourceExhausted in production."

- **Short term:** exponential backoff with jitter (`google.api_core.retry` / `tenacity`) plus a client-side token bucket so you fail fast instead of hammering.
- **Capacity:** quotas are per project × region × model — spread across regions or request an increase.
- **Durable fix:** **Provisioned Throughput** for critical paths, pay-as-you-go as spillover.
- **Architectural:** decouple with Pub/Sub so bursts queue instead of erroring; move non-interactive work to batch prediction.
- **Reduce demand:** semantic caching of repeated prompts, context caching for shared prefixes, route easy requests to Flash and only hard ones to Pro.
- **Observability:** alert on the 429 **rate** specifically, not just overall errors.

---

### S10. "Legal says customer PII must never leave our VPC or be used for training."

- Vertex AI **does not** use your prompts or outputs to train Google's foundation models — say this first.
- **Network:** Private Service Connect / Private Google Access; **VPC Service Controls** perimeter around Vertex AI, GCS and BigQuery to block exfiltration.
- **Data:** **Cloud DLP** inspect + de-identify (tokenise/mask) PII *before* it reaches the prompt; re-identify only on the trusted side.
- **Encryption:** CMEK on Vertex resources, GCS buckets and the pipeline root.
- **Residency:** pin `location` (e.g. `europe-west4`), confirm model availability there, avoid the `global` endpoint when residency is mandated.
- **Access:** least-privilege SAs (`roles/aiplatform.user`, never Editor), Workload Identity, Cloud Audit Logs on every predict call.
- **Retention:** disable or TTL request-response logging if it would persist PII.

---

## D. Operations & Troubleshooting

### S11. "Accuracy was 92% at launch; three months later the business says it's broken — but nothing is erroring."

Classic **drift**: the system is healthy, the world changed.

- Distinguish **data drift** (inputs moved), **concept drift** (input→label relationship moved) and an upstream **data-quality break** (a feature silently became null after a schema change).
- Enable **Vertex AI Model Monitoring** with the training set as baseline; alert on skew/drift thresholds.
- Compare training-time vs serving-time feature distributions — **training/serving skew** from duplicated preprocessing is extremely common; fix with a shared transform or Feature Store.
- Join delayed ground-truth labels back onto logged predictions in BigQuery for true accuracy tracking.
- Response: automated retraining on drift alert, behind the champion/challenger gate from S6.

---

### S12. "A prediction returns 200 but the body is empty / blocked."

Check `candidate.finish_reason` — `SAFETY`, `MAX_TOKENS`, `RECITATION`, `PROHIBITED_CONTENT`. Inspect `safety_ratings` and tune `safety_settings` (e.g. `BLOCK_ONLY_HIGH`) where the business context justifies it. Log `prompt_feedback.block_reason` so it's debuggable in prod. For `MAX_TOKENS`, raise the limit or request a shorter format. Never swallow this as a generic 200 — map it to a typed error for the caller.

---

### S13. Rapid-fire troubleshooting table

| Symptom | Likely cause / fix |
|---|---|
| `403 PERMISSION_DENIED` on predict | SA missing `roles/aiplatform.user`; API not enabled. |
| Endpoint deploy stuck 20+ min | Container not listening on `$AIP_HTTP_PORT`, or `$AIP_HEALTH_ROUTE` non-200. |
| Model uploads but predictions 500 | Serving preprocessing differs from training — check the custom prediction routine. |
| Pipeline step unexpectedly `Cached` | Mutable image tag / unchanged params — pin digests, disable caching. |
| High GPU cost, low throughput | Duty cycle <20% → move to CPU or enable dynamic batching. |
| Batch prediction very slow | Too few input shards — increase `starting_replica_count` and split input files. |
| Quota errors on custom training | Regional GPU quota — request increase or switch region/accelerator. |
| Online predict payload rejected | 1.5 MB request limit — pass a GCS URI instead of inline data. |

---

## E. Behavioural-Technical

### S14. "Tell me about a time you optimised an AI workload for cost or performance."

**STAR, with numbers:**

> **Situation** — A daily scoring service ran on a 4-replica GPU endpoint 24×7.
> **Task** — Cut cost without breaking the 6 AM SLA for downstream reports.
> **Action** — Profiled traffic in Cloud Monitoring: 98% of calls arrived in a 20-minute window. Moved the workload to a Vertex `BatchPredictionJob` triggered by a Pipeline schedule, kept a small 1-replica CPU endpoint for ad-hoc lookups, pinned image digests and enabled pipeline caching for unchanged feature-prep steps.
> **Result** — ~70% cost reduction, SLA met 30 minutes earlier, and the job became reproducible from a commit SHA.

This maps directly to the JD line *"troubleshoot and optimise AI workflows for performance and cost efficiency."*

---
---

# Part 4 — Cheat Sheets

## Decision cheat-sheet (frequently probed)

| Decision | Deciding factor |
|---|---|
| Online endpoint vs Batch prediction | Latency requirement and traffic shape. |
| Prompt engineering vs RAG vs fine-tuning | Style vs facts vs behaviour. |
| `@dsl.component` vs custom container vs `CustomTrainingJobOp` | Dependency weight and machine size. |
| AutoML vs custom training | Time-to-value vs control. |
| Cloud Run vs GKE vs Vertex Endpoint | Managed scaling vs fleet control vs built-in lineage/monitoring. |

## IAM roles you should be able to name

| Role | Needed for |
|---|---|
| `roles/aiplatform.user` | Calling predict, submitting jobs/pipelines. |
| `roles/storage.objectAdmin` | Writing the `pipeline_root` / artifacts. |
| `roles/iam.serviceAccountUser` | Submitting a job *as* a service account. |
| `roles/secretmanager.secretAccessor` | Reading secrets inside components. |
| `roles/artifactregistry.writer` | Pushing container images from CI. |

## Interview answer framework

**Problem → GCP service choice → code → security (IAM / Workload Identity / VPC-SC) → monitoring (Cloud Logging & Monitoring) → cost.**

---

*Generated as a consolidated study guide. Code targets `google-cloud-aiplatform` with KFP v2 pipeline syntax; verify model IDs and API surfaces against current Google Cloud documentation before an interview.*
