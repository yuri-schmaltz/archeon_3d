# Relatório de Auditoria do Backend: Gauntlet Loop

**Data:** 2026-10-08  
**Escopo:** API FastAPI, instalação local, serviço de inferência compartilhado, manager de jobs, persistência SQLite, uploads, SSE e mesh operations.
**Status:** remediações implementadas; instalação suportada somente local via `launcher.sh`.

## Resumo executivo

O gauntlet confirmou falhas na exposição do deployment em container, replay/cancelamento de jobs, limites de entrada e filas, retenção e estado operacional. O suporte de instalação/container foi removido em favor de um launcher local que detecta CPU/CUDA e prepara backend/frontend. Os detalhes abaixo descrevem o comportamento original e registram as remediações aplicáveis ao backend.

## Gauntlet Loop

1. **Fronteira de exposição:** comparei bind, portas publicadas, auth, CORS, rate limit e middleware de corpo.
2. **Ciclo de vida:** segui submissão, reidratação, execução, cancelamento e shutdown pelos dois caminhos de worker.
3. **Pressão de recursos:** examinei uploads, payloads persistidos, filas, assinantes SSE, retenção e operações de malha.
4. **Refutação por testes:** comparei cada hipótese com testes próximos e procurei se eles verificam o efeito final, não apenas o estado intermediário.

## Achados Confirmados e Remediações

### P1 — O deployment anterior em container podia expor a API sem autenticação (removido)

O arquivo de Compose anterior fixava bind remoto com chave opcional. Essa configuração não existe mais: Dockerfiles, Compose, proxy Nginx/Caddy e automações associadas foram removidos. O launcher local usa loopback por padrão; o servidor também rejeita bind não-loopback sem `POLYFORGE_API_KEY`.

Evidência remanescente: [server.py](../../hy3dgen/api/server.py), [launcher.sh](../../launcher.sh).

### P1 — Reidratação deixa jobs ativos presos no modo padrão

`PriorityRequestManager.rehydrate()` reconstitui jobs e os coloca em `manager.queue`. Quando `inference_service` está configurado, `start()` inicia o worker do serviço e o listener de eventos, mas não inicia `_process_queue()` nessa fila. Como o compartilhamento está habilitado por padrão, jobs persistidos como `queued`/`processing` podem aparecer novamente como `queued` e nunca ser executados após reinício.

Evidência: [manager.py](../../hy3dgen/api/manager.py), [inference_service.py](../../hy3dgen/api/inference_service.py), [test_rehydrate.py](../../tests/test_rehydrate.py).

**Implementado:** reidratação submete jobs ao `InferenceService` com UID persistido; submissão é idempotente por UID. Se a fila limitada estiver cheia durante recuperação, o job é marcado `failed` com motivo e instrução de resubmissão, em vez de ficar preso silenciosamente. Há teste do caminho compartilhado.

### P1 — Cancelamento no modo compartilhado não cancela o trabalho

O endpoint chama `manager.cancel_job()`. Esse método altera apenas o estado do objeto no manager e não chama `InferenceService.cancel()`. Mesmo se o serviço for chamado, `cancel()` remove o job de `_jobs`, mas não o remove da fila; `_run()` executa qualquer item retirado da fila sem consultar essa marcação. O resultado pode consumir inferência e depois sobrescrever `cancelled` com `completed`.

O adaptador também não traduz os estágios `LOADING_MODEL`/`SHAPE_GENERATION` para `JobStatus.PROCESSING`; o endpoint usa esse status para decidir o conflito de cancelamento. Assim, durante inferência o cliente pode observar `queued` e receber uma falsa confirmação de cancelamento.

Evidência: [routes.py](../../hy3dgen/api/routes.py), [manager.py](../../hy3dgen/api/manager.py), [inference_service.py](../../hy3dgen/api/inference_service.py), [test_inference_service.py](../../tests/test_inference_service.py).

**Implementado:** o serviço rastreia UID ativo, ignora itens já cancelados, recusa cancelar trabalho em andamento e publica estado terminal; o manager delega cancelamento, traduz estágios ativos como `processing`, e a rota responde `409` quando não é possível cancelar. Testes cobrem fila e job ativo.

### P1 — Limites de entrada não contêm todo o consumo de memória

O middleware anterior rejeitava apenas `Content-Length` acima do limite; corpos sem esse header não eram contados durante a leitura. Além disso, schemas aceitavam strings base64 sem limites individuais de bytes ou dimensões; imagens comprimidas podiam expandir muito ao serem decodificadas.

Evidência: [server.py](../../hy3dgen/api/server.py), [schemas.py](../../hy3dgen/api/schemas.py), [inference.py](../../hy3dgen/inference.py), [polyforge_frontend/README.md](../../polyforge_frontend/README.md).

**Implementado:** middleware ASGI conta chunks mesmo sem `Content-Length`; decoder base64 impõe 10 MiB por imagem e 30 MiB por malha antes/depois da decodificação; imagem é limitada a 25 megapixels. Limites são anunciados por capabilities. Limite de geometria/timeout de GLB permanece pendente.

### P1 — Fila e filas SSE não têm backpressure

O serviço usa `asyncio.Queue()` sem `maxsize`, e cada job retém parâmetros que podem conter imagens ou malhas em base64. O valor `queue_depth` anunciado deriva de `max_history`, mas não limita submissões. Os queues de eventos e de snapshots SSE também são ilimitados; um cliente lento pode acumular eventos/snapshots completos indefinidamente. Rate limiting por IP reduz cadência, mas não limita memória total nem a quantidade de jobs pendentes.

Evidência: [inference_service.py](../../hy3dgen/api/inference_service.py), [manager.py](../../hy3dgen/api/manager.py), [routes.py](../../hy3dgen/api/routes.py).

**Implementado:** fila do manager e serviço limitada por `POLYFORGE_MAX_QUEUE_SIZE` (default 4); submissões cheias recebem `503` com `Retry-After`; estado expõe profundidade/capacidade reais. Filas SSE de eventos e snapshots têm um item e coalescem para o estado mais recente. Shutdown drena pendências sem bloquear numa fila cheia.

## Achados de confiabilidade e operação

### P2 — Retenção não roda no caminho compartilhado padrão (corrigido)

`_aggressive_cleanup()` é chamado pelo loop embutido do manager após execução. Com `InferenceService`, o manager apenas espelha eventos e não aciona essa limpeza. O helper que remove artefatos antigos existe, mas não encontrei agendamento/chamada no fluxo de inicialização ou execução. Portanto `max_history`/`max_age_seconds` não são aplicados de forma consistente no modo padrão; o SQLite e o diretório de artefatos podem crescer indefinidamente.

Evidência: [manager.py](../../hy3dgen/api/manager.py), [test_manager_eviction.py](../../tests/test_manager_eviction.py).

**Implementado:** tarefa periódica executa retenção após readiness e a cada cinco minutos; terminais também disparam cleanup. Idade e `max_history` removem registro e artefato; exclusão de arquivos é confinada ao `SAVE_DIR`.

### P2 — Warm-up bloqueia a resposta e reporta estado incorreto

`POST /v1/models/load` aguarda `service.warmup()`. No serviço compartilhado, `warmup()` espera o download/carregamento terminar em `to_thread` antes de retornar; logo a chamada HTTP pode durar minutos, embora a documentação da rota prometa resposta imediata. Depois disso, retorna `loading`, e o schema de status mantém `loading=False`.

Evidência: [routes.py](../../hy3dgen/api/routes.py), [inference_service.py](../../hy3dgen/api/inference_service.py), [test_inference_service.py](../../tests/test_inference_service.py).

**Implementado:** warm-up idempotente retorna imediatamente, expõe estado e timestamps, registra falhas e compartilha lock com inferência para não carregar pesos em paralelo à geração.

### P2 — Health e estatísticas declaram modelo descarregado após carga

No modo compartilhado, o worker pertence a `InferenceService._worker`. `/v1/models/status` conhece essa referência, mas `/health` e `/v1/admin/stats` consultam `manager.worker`, que não é atualizado pelo adaptador. Após a primeira carga, esses dois endpoints podem continuar dizendo `model_loaded=false`.

Evidência: [server.py](../../hy3dgen/api/server.py), [routes.py](../../hy3dgen/api/routes.py), [manager.py](../../hy3dgen/api/manager.py).

**Implementado:** manager expõe `model_loaded` consultando o worker ativo; health e admin usam essa propriedade, e model status lê estado/timestamps públicos do serviço.

### P2 — Banco guarda payloads de upload sem permissões explícitas

O SQLite persiste `request_blob`, incluindo payloads base64, e o diretório pai é criado sem modo restritivo explícito. Em instalações multiusuário com umask comum, isso pode deixar prompts, imagens e malhas legíveis por outros usuários locais.

Evidência: [persistence.py](../../hy3dgen/api/persistence.py), [test_persistence.py](../../tests/test_persistence.py).

**Implementado:** diretório de estado novo usa `0700`; SQLite e arquivos WAL/SHM usam `0600`. Payloads continuam armazenados em claro, agora privados ao usuário do processo; criptografia em repouso permanece uma decisão operacional.

## Pendências Residuais

- **Replay acima da capacidade:** corrigido. O worker compartilhado inicia antes da reidratação e `submit_recovered()` aguarda slots, replayando jobs em batches sem exceder a capacidade; há teste com três jobs e capacidade um.
- **Persistência assíncrona:** transições emitidas em tarefas separadas ainda podem gravar fora de ordem; serializar por UID e aguardar tarefas pendentes no shutdown.
- **Semântica de prioridade:** manager legado usa `PriorityQueue`, mas o serviço compartilhado usa FIFO. Unificar a política ou documentar que prioridade só existe no modo legado.
- **URLs assinadas:** configurar uma base URL pública validada em vez de derivá-la implicitamente de `Host`/headers de proxy.
- **Mesh operations:** limitar concorrência, faces/vértices e custo de introspecção; inferência serializada não protege esse executor.
- **Dados em repouso:** SQLite agora tem permissões privadas, mas `request_blob` continua sem criptografia.
- **Erros/logs:** padronizar erros públicos e logging estruturado com `job_uid`; evitar traceback direto em stdout.
- **Inferência real:** os testes usam stub sem CUDA; validar warm-up, geração, cancelamento em thread e memória em uma máquina com GPU antes de release.

## Próximas Ações

1. Limitar CPU/memória concorrente de meshops e definir limites geométricos.
2. Serializar persistência por job e decidir se payloads precisam de criptografia em repouso.

## Verificação e limitações

- Criado ambiente temporário Python 3.12.13 em `/tmp/polyforge-py312-venv`, compatível com `requires-python`; o `.venv` preexistente Python 3.14 foi preservado.
- O perfil `.[test]` e os requirements agora declaram NetworkX para habilitar `trimesh.split()`; o ambiente temporário também recebeu essa dependência.
- Regressão core (service, recuperação, manager, API/auth, config, DB, URLs assinadas, SSE, retenção, meshops, métricas, readiness e launcher): **218 passed, 0 failed**. Inclui replay de três jobs com capacidade um.
- Concorrência HTTP, SSE stress e eviction sob carga: **9 passed, 0 failed** na rodada anterior; total validado: **227 passed, 0 failed, 4.670 warnings**.
- `bash -n launcher.sh`, `launcher.sh --help`, YAML de CI/Dependabot e ausência de Dockerfiles/Compose/proxy foram validados. Diagnósticos sem erros.
- A execução usou um stub mínimo de `torch` com CUDA indisponível apenas para liberar testes que fazem gate por import. Nenhum modelo foi carregado; inferência real, GPU e memória CUDA continuam sem validação.
- Os warnings são principalmente chamadas a `datetime.utcnow()` nos fixtures de testes e não causaram falhas.

O repositório já registra oportunidades semelhantes em [PLANO_DE_MELHORIAS_2026-10-04.md](PLANO_DE_MELHORIAS_2026-10-04.md#L170); este relatório acrescenta a confirmação dos caminhos específicos do serviço compartilhado habilitado por padrão.