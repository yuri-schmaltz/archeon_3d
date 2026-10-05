# Como baixar / carregar os modelos

Os modelos do Archeon são **carregados sob demanda** quando o primeiro
job é submetido (ou via `POST /v1/models/load` para pré-aquecer).
Não é preciso baixar nada manualmente.

## Variáveis de ambiente

Todas opcionais. Defaults vêm do `pyproject.toml`.

| Variável | Default | Notas |
|---|---|---|
| `ARCHEON_DEVICE` | `cuda` | `cuda` ou `cpu` |
| `ARCHEON_MODEL` | `tencent/Hunyuan3D-2` | Modelo principal (≈8 GB) |
| `ARCHEON_MODEL_SUBFOLDER` | `hunyuan3d-dit-v2-0` | Subpasta |
| `ARCHEON_MINI_MODEL` | `tencent/Hunyuan3D-2mini` | Modelo leve (≈4 GB) |
| `ARCHEON_MULTIVIEW_MODEL` | `tencent/Hunyuan3D-2mv` | Para modo 4 vistas |
| `ARCHEON_USE_SHARED_INFERENCE` | `true` | `false` desliga o `InferenceService` |

## Recomendações

- **RTX 3060 (12 GB) ou similar**: use o **mini** (~4 GB na VRAM, ~30 s
  por job):
  ```bash
  ARCHEON_MODEL=tencent/Hunyuan3D-2mini \
  ARCHEON_MODEL_SUBFOLDER=hunyuan3d-dit-v2-mini-turbo \
  ./launcher.sh
  ```
- **RTX 4090 / A100 (24+ GB)**: o modelo full é melhor (~8 GB, ~1 min).
- **Apple Silicon / CPU**: use o mini e espere (~5 min por job).

## Como pré-carregar

Há **três** formas:

1. **Pela UI** — System page → botão "Carregar modelo agora". Mostra
   status ao vivo em `GET /v1/models/status`.
2. **Pela API** — `curl -X POST http://127.0.0.1:8081/v1/models/load`
3. **Standalone (sem subir o servidor)** —
   ```bash
   python scripts/download_models.py --scope all
   ```
   Útil em conexões lentas, imagens Docker, ou CI.

## Onde ficam os pesos

Cache padrão do Hugging Face: `~/.cache/huggingface/hub/`. Você pode
apontar para outro lugar com `HF_HOME=/caminho`.

## Troubleshooting

### `No module named 'diffusers'`
O launcher caiu no fallback `[dev]` porque `diso` falhou no build
(CUDA mismatch, geralmente). A correção automática do launcher
instala `diffusers`, `transformers`, `accelerate`, etc. individualmente
— basta reexecutá-lo com `rm .archeon_launcher.stamp && ./launcher.sh`.

### `transformers` muito novo
`transformers 5.x` mudou o formato dos state_dicts e quebra o load do
Hunyuan3D-2. O launcher pina `transformers>=4.50,<5` para evitar isso.

### `diso` não compila
`diso` exige `nvcc` e CUDA igual ao torch. **Não é bloqueante**: o
runtime tem fallback automático para `mc` (marching cubes padrão).
O `mc` é ~30 % mais lento mas produz meshes idênticos.

### O modelo está carregando há minutos
Na primeira execução o download de 4-8 GB pode demorar (depende da
banda). Após o download, o cache HF é reutilizado — execuções
subsequentes são instantâneas.
