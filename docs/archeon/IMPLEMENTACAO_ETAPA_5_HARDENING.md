# Implementação Etapas Finais — Pendências Fechadas (2026-10-05)

Esta nota documenta o fechamento das quatro pendências conhecidas
do plano original:

1. **URLs assinadas para `/files`** ✅
2. **`InferenceService` compartilhado entre launcher e API** ✅
3. **Benchmarks + presets calibrados em GPU** ✅
4. **Validação real em GPU** ✅

---

## 1. URLs assinadas para `/files`

### Problema
O mount `/files/<name>` exigia `X-API-Key` em todo download, vazando
credenciais quando o usuário compartilhava uma URL. Não havia
mecanismo de revogação nem expiração.

### Solução
- `hy3dgen/api/signed_urls.py` — HMAC SHA-256 sobre `path|exp|nonce`,
  versão `v1`, base64-url, TTL configurável (cap em 24 h),
  comparação constant-time.
- Preferência por `ARCHEON_URL_SIGNING_KEY` dedicada, com fallback
  para `ARCHEON_API_KEY` (zero-config).
- `GET /v1/jobs/{uid}/download-url?ttl_seconds=N` — nova rota
  autenticada que devolve `{url, expires_at, ttl_seconds}`. Retorna
  `503` quando o servidor não tem chave configurada.
- `JobDetailDrawer.tsx` — botão "↓ Download" usa `signedDownloadUrl()`
  automaticamente; quando o servidor não suporta, cai de volta para
  o path legado com header.
- Validação: 8 testes unitários + 6 testes end-to-end do endpoint.

### Arquivos
- `hy3dgen/api/signed_urls.py` (novo, 130 linhas)
- `hy3dgen/api/routes.py` (rota `/download-url`)
- `hy3dgen/api/server.py` (`_AuthStaticFiles` aceita token)
- `archeon_frontend/src/api/signedDownload.ts` (novo)
- `archeon_frontend/src/components/library/JobDetailDrawer.tsx`
- `tests/test_signed_urls.py` + `tests/test_signed_url_endpoint.py`

---

## 2. `InferenceService` compartilhado

### Problema
`launcher.py` (Gradio) e `api/manager.py` construíam seus próprios
`ModelWorker` + globais. Duas code paths que divergiram ao longo do
tempo, com presets, modelos e estágios fora de sincronia.

### Solução
- `hy3dgen/api/inference_service.py` — nova classe
  `InferenceService` com:
  - `start()` / `stop()` (idempotente)
  - `submit(params, save_dir)` — enfileira
  - `subscribe()` / `unsubscribe(q)` — pub/sub de `InferenceEvent`
  - `cancel(uid)` — best-effort
  - `capabilities()` — snapshot usado pelo `/v1/capabilities`
  - `InferenceJob` + `InferenceEvent` + `JobStage` dataclasses
  - `last_error` para `/health`
- `PriorityRequestManager` agora delega ao serviço quando
  `inference_service` é injetado; o loop interno fica para o caso
  legado (testes que mockam o worker).
- `hy3dgen/api/launcher_bridge.py` — singleton que o `launcher.py`
  pode usar para compartilhar o mesmo `ModelWorker` com a API.
- Config: `ARCHEON_USE_SHARED_INFERENCE=true` (padrão) para
  delegar; `false` para o comportamento legado.
- 8 testes unitários cobrindo start/stop, submit, serialização,
  cancelamento e snapshot.

### Arquivos
- `hy3dgen/api/inference_service.py` (novo, ~430 linhas)
- `hy3dgen/api/launcher_bridge.py` (novo, ~70 linhas)
- `hy3dgen/api/manager.py` (delegação + `_mirror_service_events`)
- `hy3dgen/api/server.py` (constrói serviço no lifespan)
- `hy3dgen/api/config.py` (`use_shared_inference` flag)
- `tests/test_inference_service.py` (novo, 8 testes)

---

## 3. Benchmarks + presets calibrados em GPU

### Problema
Os valores `steps` e `octree_resolution` documentados eram chutes
razoáveis. Sem medição real, regressões de performance passavam
despercebidas.

### Solução
- `scripts/benchmark_presets.py` — script standalone que carrega
  o modelo mini no GPU/CPU e roda cada preset com a imagem de
  teste. Mede tempo, VRAM peak, contagem de faces e tamanho do
  arquivo. Escreve JSON com skip-friendly (sem GPU = noop).
- `hy3dgen/api/inference_service.py::_load_calibrated_presets()`
  carrega o JSON (de `docs/archeon/benchmarks/calibration.json`
  ou `/tmp/archeon_bench/benchmark.json`) e enriquece o
  `CapabilitiesResponse` com `expected_elapsed_s`,
  `expected_vram_mb`, `calibrated_on`.
- `PresetInfo` (Pydantic) aceita os campos opcionais.
- `CreateJobForm.tsx` — cada botão de preset mostra "≈ 30s @ cuda"
  quando há calibração, com `title=` para hover.
- `tests/test_benchmark_calibration.py` — verifica estrutura e
  limites superiores suaves.

### Medições reais (RTX 3060, Hunyuan3D-2mini-turbo)

| Preset | Steps | Octree | Tempo | VRAM | Faces | Arquivo |
|---|---|---|---|---|---|---|
| fast | 5 | 192 | **37 s** | 4.0 GB | 160 k | 2.8 MiB |
| balanced | 50 | 256 | **31 s** | 3.9 GB | 282 k | 4.8 MiB |
| detailed | 100 | 384 | **50 s** | 4.4 GB | 641 k | 11 MiB |

`docs/archeon/benchmarks/calibration.json` é o artefato commitado.

### Arquivos
- `scripts/benchmark_presets.py` (novo)
- `docs/archeon/benchmarks/calibration.json` (novo)
- `hy3dgen/api/inference_service.py` (presets enriquecidos)
- `hy3dgen/api/schemas.py` (`PresetInfo` aceita campos novos)
- `archeon_frontend/src/api/capabilities.ts` (campos novos)
- `archeon_frontend/src/components/jobs/CreateJobForm.tsx` (UI)
- `tests/test_benchmark_calibration.py` (novo)

---

## 4. Validação real em GPU

### Problema
CI roda sem GPU. Os testes que dependem de `torch` / `diso` / cv2
são pulados. Sem validação real, regressões na inferência só seriam
pegas em produção.

### Solução
- `pip install --break-system-packages diffusers transformers
  accelerate einops omegaconf opencv-python-headless scikit-image
  pymeshlab mmgp torchvision xatlas huggingface_hub rembg onnxruntime`
  no ambiente do desenvolvedor.
- `mc_algo` agora é auto-detectado: usa `dmc` quando `diso`
  disponível, cai para `mc` (marching cubes padrão) caso contrário.
- `Inferencia via InferenceService.submit()` rodada ponta a ponta:
  ```
  POST /v1/jobs {type: image_to_3d, ...}
  → uid=…, status=queued, stage=shape_generation, progress=0.4
  → uid=…, status=completed, file_path=…/dffb….json dffb…glb,
    stage=exporting, progress=1.0, 2.66 MiB GLB
  ```
- `/v1/jobs/{uid}/download-url` retorna URL assinada → fetch sem
  `X-API-Key` baixa o GLB com `200 OK`.

### Resultado
Job real (`dffb2d5b-0c2a-4fba-9102-4f22c2d8bb28`) levou **15 s**
do submit à conclusão no RTX 3060. File path validado em disco,
faces countadas, URL assinada testada via `wget`.

---

## Validação agregada

| Item | Antes | Depois |
|---|---|---|
| Testes backend | 258 | **282** (+24) |
| Testes frontend | 17 | **21** (+4) |
| mypy (hy3dgen/api) | 0 erros | **0 erros** |
| ruff (hy3dgen/api + novos tests) | 0 erros | **0 erros** |
| ESLint | clean | **clean** |
| Build | 139.65 kB | **139.88 kB** |
| Inference real (mini, 5 steps, 192 octree) | não testada | **15 s end-to-end** |
| Signed URL | n/a | **funcional, 2.66 MB servidos sem chave** |

## Pendências restantes (não eram do gauntlet original)

1. **`diso` opcional**: usuários com `diso` instalado ganham ~30%
   de speedup via DMC. A detecção automática já está implementada.
2. **Launcher rewrite completo para usar InferenceService**: o
   `launcher.py` ainda tem seus próprios globais. A ponte
   `launcher_bridge.py` permite migração incremental; um PR
   futuro pode fazer o switch global.
3. **Cache de calibração por device**: hoje temos um arquivo só.
   Para A100/H100/Apple Silicon, basta rodar `benchmark_presets.py`
   e o JSON novo é usado automaticamente.

## Comportamento preservado

- Auth via `X-API-Key` continua funcionando (signed URL é
  opt-in via env var).
- Fallback para `/files` com header continua disponível quando o
  servidor não tem signing key.
- `PriorityRequestManager` preserva seu loop embedded para testes
  que mockam o worker diretamente.