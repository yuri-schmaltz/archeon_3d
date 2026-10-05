# Implementação Etapa 2 — contratos, operação e capabilities

Data: 04/10/2026. Referências:
- [Plano Fase 2](PLANO_FASE_2_2026-10-04.md)
- [Diagnóstico inicial](PLANO_DE_MELHORIAS_2026-10-04.md)
- [Implementação Etapa 1](IMPLEMENTACAO_ETAPA_1.md)

Esta nota resume o que foi entregue na Etapa 2 e o que permanece
aberto para as próximas etapas. As alterações ficam em área de
trabalho (sem commit), seguindo o critério da Etapa 1.

## Mudanças entregues

#### Endpoint `/v1/capabilities`

- Novo endpoint autenticado que devolve o estado dinâmico do servidor:
  - `modes` — modos disponíveis + motivo (`text`, `image`, `multiview`,
    `texture`).
  - `models` — checkpoint carregado por pipeline (`shape`, `multiview`,
    `texture`, `text_to_image`).
  - `presets` — três perfis calibrados (`fast`, `balanced`, `detailed`).
  - `limits` — tamanhos máximos de imagem, mesh e payload JSON.
  - `version` — versão do servidor.
- Implementado em `hy3dgen/api/routes.py` via
  `manager.capabilities()` (`hy3dgen/api/manager.py`).

#### Progresso por etapa (`stage` + `stage_progress`)

- `JobResponse` agora carrega `stage` (string) e `stage_progress`
  (float 0–1) opcionais.
- O manager emite transições durante a execução: `loading_model`,
  `shape_generation`, `exporting` (o `texturing` continua deuses dentro
  do worker para evitar quebra da arquitetura atual).
- Eventos SSE agora carregam apenas campos alterados
  (`exclude_defaults=True, exclude_none=True`).

#### `/files` protegido por API key

- `_AuthStaticFiles` (`hy3dgen/api/server.py`) é um wrapper sobre
  `StaticFiles` que valida `X-API-Key` antes de servir o arquivo.
- Em modo `auth`, retorna 401 sem chave, 403 com chave errada, 200 com
  chave correta.
- Sem chave configurada (dev local), o comportamento é aberto
  (idêntico ao atual).

#### Limite de corpo da requisição

- Middleware `http` retorna 413 quando o `Content-Length` excede
  64 MiB. Evita que payloads enormes consumam memória/tempfile antes
  da validação Pydantic.

#### Separação de retenção (DB × disco)

- `JobStore.delete_older_than` continua sendo o caminho para limpar o
  banco (não toca em arquivos).
- Novo `JobStore.list_older_than` lista os trabalhos terminais antigos
  sem removê-los, usado pelo gerenciador para inspecionar artefatos.
- Novo `manager.cleanup_files_older_than(save_dir)` remove apenas
  arquivos em disco, preservando o banco. Os dois caminhos podem rodar
  com políticas independentes (ex.: manter DB por 24 h, manter arquivos
  por 7 dias).

#### Frontend: hook de capabilities + UI adaptativa

- `src/api/capabilities.ts` — hook `useCapabilities` (com fallback
  permissivo) + `FALLBACK_CAPABILITIES` exportado para testes.
- `ModeChips` aceita agora `availability` opcional. Modos indisponíveis
  são visualmente desativados, recebem `aria-disabled`, tooltip com o
  motivo e bloqueiam clique/arrow keys.
- `CreateJobForm` lê o estado das capabilities e cai para o primeiro
  modo disponível se o atual ficar indisponível (ex.: servidor
  reiniciou sem o modelo carregado).

## Evidências de validação

| Verificação | Resultado |
| --- | --- |
| Suíte principal do backend (`TZ=America/Sao_Paulo`) | **204 aprovados**, 179 warnings |
| Suíte Etapa 2 (`tests/test_etapa_2.py`) | **11 aprovados** |
| Mypy em `hy3dgen/api` | **0 erros** (10 módulos) |
| Frontend ESLint | **0 erros** |
| Frontend build | **OK** — 415.58 kB / 136.30 kB gzip |
| Frontend Vitest (capabilities + generation) | **7 aprovados** |
| Vitest configurado com `jsdom` | OK |

A nova lógica Etapa 2 (`stage`/`stage_progress`, capabilities, files
auth, body limit, retention split, capabilities UI) está coberta por
testes. As partes que ainda exigem GPU real ou subprocessos para
validação (download de pesos, geração de malha, build CUDA) seguem
fora do escopo desta execução.

## Pendências para Etapas 3–5

1. **Roteamento completo** com 4 páginas (Criar / Biblioteca / Sistema /
   Configurações), bottom-tabs no mobile e sidebar persistente no desktop.
2. **Viewer 3D local** empacotado (substituir o `<model-viewer>` via CDN
   por bundle local) com loading/error/reset.
3. **Biblioteca paginada** com busca e detalhe de trabalho.
4. **Drag-and-drop** e prévia ampliada para uploads.
5. **i18n pt-BR + en** com toggle persistido.
6. **Testes E2E** com Playwright cobrindo os fluxos de criação,
   acompanhamento, conclusão e reutilização.
7. **`InferenceService` compartilhado** entre launcher e API.
8. **Benchmarks + presets calibrados** em GPU de referência.
9. **URLs assinadas** para compartilhamento seguro de artefatos quando o
   servidor expõe `/files` em ambiente compartilhado.

Os critérios de aceite globais estão documentados em
[PLANO_FASE_2_2026-10-04.md](PLANO_FASE_2_2026-10-04.md).
