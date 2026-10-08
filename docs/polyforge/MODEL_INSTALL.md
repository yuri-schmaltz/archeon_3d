# Como baixar / carregar os modelos

Os modelos do PolyForge são **carregados sob demanda** quando o primeiro
job é submetido (ou via `POST /v1/models/load` para pré-aquecer).
Não é preciso baixar nada manualmente.

## Variáveis de ambiente

Todas opcionais. Defaults vêm do `hy3dgen.api.config.Settings`.

| Variável | Default | Notas |
|---|---|---|
| `POLYFORGE_DEVICE` | `cuda` | `cuda` ou `cpu` |
| `POLYFORGE_MODEL` | `tencent/Hunyuan3D-2` | Modelo principal (≈8 GB) |
| `POLYFORGE_MODEL_SUBFOLDER` | `hunyuan3d-dit-v2-0` | Subpasta |
| `POLYFORGE_MINI_MODEL` | `tencent/Hunyuan3D-2mini` | Modelo leve (≈4 GB) |
| `POLYFORGE_MULTIVIEW_MODEL` | `tencent/Hunyuan3D-2mv` | Para modo 4 vistas |
| `POLYFORGE_T2I_MODEL` | `Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled` | Referência de imagem do `text_to_3d` |
| `POLYFORGE_HF_HOME` | `HF_HOME` ou cache padrão | Substitui `HF_HOME` para downloads/carregamentos do backend |
| `POLYFORGE_USE_SHARED_INFERENCE` | `true` | `false` desliga o `InferenceService` |

## Recomendações

- **RTX 3060 (12 GB) ou similar**: use o **mini** (~4 GB na VRAM, ~30 s
  por job):
  ```bash
  POLYFORGE_MODEL=tencent/Hunyuan3D-2mini \
  POLYFORGE_MODEL_SUBFOLDER=hunyuan3d-dit-v2-mini-turbo \
  ./launcher.sh
  ```
- **RTX 4090 / A100 (24+ GB)**: o modelo full é melhor (~8 GB, ~1 min).
- **Apple Silicon / CPU**: use o mini e espere (~5 min por job).

## Modo texto (`text_to_3d`)

O modo texto usa um pipeline separado de texto-para-imagem antes da
reconstrução 3D:

- Modelo padrão: `Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled`.
- Pesos em cache: cerca de 14,5 GB.
- Esse pipeline permanece na CPU nesta implantação porque não cabe na VRAM
  junto com o modelo de forma em GPUs de 12 GB.
- Com as configurações fixas atuais, a etapa de referência pode levar horas
  na CPU e ocupa a fila serial. Prefira `image_to_3d` quando precisar de
  resposta rápida.
- `POST /v1/models/load` pré-aquece apenas o modelo de forma. Use
  `GET /v1/models/status` e observe `text_to_image_loaded` antes de concluir
  que o modo texto está pronto.

## Como pré-carregar

Há **quatro** formas:

1. **Na instalação** — `./launcher.sh --download-models` baixa os pesos
   logo após instalar as dependências. Com `--model-scope` você escolhe
   o que baixar: `shape`, `multiview`, `tex`, `t2i` ou `all` (padrão).
   Sem flags, o launcher pergunta uma vez se o terminal for interativo;
   em CI/scripts, use `POLYFORGE_DOWNLOAD_MODELS=1` (ou `0` para pular
   sem perguntar) e `POLYFORGE_MODEL_SCOPE=t2i`, por exemplo.
2. **Pela UI** — System page → botão "Carregar modelo agora". Mostra
   status ao vivo em `GET /v1/models/status`.
3. **Pela API** — `curl -X POST http://127.0.0.1:8081/v1/models/load`
4. **Standalone (sem subir o servidor)** —
   ```bash
   .venv/bin/python scripts/download_models.py --scope all
   # ou: make models | make models SCOPE=t2i
   ```
  Útil em conexões lentas, instalações locais demoradas ou CI.

## Onde ficam os pesos

Cache padrão do Hugging Face: `~/.cache/huggingface/hub/`. Você pode
apontar para outro lugar com `HF_HOME=/caminho` ou, para o backend,
`POLYFORGE_HF_HOME=/caminho`.

## Troubleshooting

### `No module named 'diffusers'`
O launcher caiu no fallback `[dev]` porque `diso` falhou no build
(CUDA mismatch, geralmente). A correção automática do launcher
instala `diffusers`, `transformers`, `accelerate`, etc. individualmente
— basta reexecutá-lo com `rm .polyforge_launcher.stamp && ./launcher.sh`.

### `transformers` muito novo
`transformers 5.x` mudou o formato dos state_dicts e quebra o load do
Hunyuan3D-2. O launcher pina `transformers>=4.50,<5` para evitar isso.

### `T5Tokenizer` vira `Placeholder` e o pipeline HunyuanDiT não carrega
Falta o `sentencepiece`, exigido pelo tokenizador T5. Instale as
dependências ML completas (`requirements.txt` ou `.[ml]`) e reinicie o
backend; não basta baixar os pesos novamente.

### `diso` não compila
`diso` exige `nvcc` e CUDA igual ao torch. **Não é bloqueante**: o
runtime tem fallback automático para `mc` (marching cubes padrão).
O `mc` é ~30 % mais lento mas produz meshes idênticos.

### O modelo está carregando há minutos
Na primeira execução o download de 4-8 GB pode demorar (depende da
banda). Após o download, o cache HF é reutilizado — execuções
subsequentes são instantâneas.
