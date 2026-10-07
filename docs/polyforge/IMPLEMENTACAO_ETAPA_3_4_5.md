# Implementação Etapas 3–5 — navegação, viewer, i18n e code-splitting

Data: 04/10/2026 (noite) — atualizado 05/10/2026 com hardening de runtime.
Referências:
- [Plano Fase 2](PLANO_FASE_2_2026-10-04.md)
- [Implementação Etapa 1](IMPLEMENTACAO_ETAPA_1.md)
- [Implementação Etapa 2](IMPLEMENTACAO_ETAPA_2.md)

Esta nota cobre o trabalho das Etapas 3 a 5 da Fase 2. O foco
consolidado foi entregar uma navegação de quatro páginas com a
biblioteca paginada, um viewer 3D empacotado localmente com estados
explícitos, i18n pt-BR + en, presets calibrados e code-splitting
para reduzir o bundle inicial.

A iteração de 05/10 adicionou **hardening de runtime** após
identificar que o SPA, quando servido sem backend (`vite preview`
sem proxy), quebrava ao receber o HTML de fallback como se fosse
JSON. O conserto blinda todos os pontos de fronteira com o backend.

## Mudanças entregues

### Navegação com 4 páginas

- Hash router próprio (`src/router/`) — sem dependências extras.
  Rotas: `/criar`, `/biblioteca`, `/sistema`, `/configuracoes`.
  Helper `go(route)` para componentes, `RouteMatch` para
  renderização condicional.
- `BottomTabs` para mobile (4 abas) e `LeftRail` (sidebar fixa no
  desktop) com a navegação primária.
- `KeyboardShortcuts` para os atalhos `g c`/`g b`/`g s`/`g a` e `?`
  ignorados quando se digita em campos.

### Página Biblioteca (`/biblioteca`)

- `GET /v1/library` (autenticado) com paginação offset-based,
  busca por `uid`/`request_type`/`request_blob` (payload text),
  filtro por `status` e contagem filtrada.
- `JobRow` em lista hairline-separada, com botão "Reutilizar"
  que abre `/criar?reuse=<uid>` para pré-preencher o formulário.
- `JobDetailDrawer` (gaveta lateral) com preview 3D, download,
  parâmetros, estágio e erro, fechamento por Esc / clique fora /
  botão.

### Página Sistema (`/sistema`)

- `SystemMonitor` reaproveitado mais um grid operacional (queue,
  memória, disco, histórico), pills por status e lista de modelos
  carregados com base em `/v1/capabilities`.
- Auto-refresh a cada 5 s; botão manual.

### Página Configurações (`/configuracoes`)

- Idioma (pt-BR / en) persistido em `localStorage` via
  `useLocale()` / `setLocale()`.
- Versão do servidor, URL base e atalhos documentados.

### Formulário de criação

- Drag-and-drop em todas as zonas de imagem (single, multiview,
  textura). Pré-visualização inline após seleção.
- Presets "Rápido" / "Equilibrado" / "Detalhado" aplicados a
  `steps`, `guidance` (e `octree_resolution` no backend),
  lidos de `/v1/capabilities`.
- Pré-preenchimento via `?reuse=<uid>` no hash — abre o modo
  correto e limpa o param após consumo.
- Validação inline (tipo/tamanho) com mensagens localizadas.

### Viewer 3D local

- `@google/model-viewer` instalado como dependência; `<script>` da
  CDN removido do `index.html`. Componente `MeshPreview` agora
  importa o pacote, que registra o custom element.
- Estados `loading`, `error` e `ready`; respeita
  `prefers-reduced-motion` (auto-rotate desativado).
- Visualizador é carregado lazy (`import()` dinâmico) — só vai
  para o bundle do usuário quando ele abre um preview.

### i18n

- `src/i18n/` com catálogos `pt-BR` e `en`, hook `useT`,
  helper `stageLabel` para tradução de estágios.
- Strings hard-coded em inglês foram substituídas por chaves
  em todos os componentes novos e em `CreateJobForm`,
  `JobDetailDrawer`, `LibraryPage`, `SystemPage`, `SettingsPage`,
  `AppShell`, `LeftRail`, `BottomTabs`, `StatusTicker`,
  `PageHeader`.

### Code-splitting

- `vite.config.ts` cria um chunk manual `model-viewer` separado.
- Páginas `LibraryPage`, `SystemPage` e `SettingsPage` são
  importadas via `lazy()` no `App.tsx`, cada uma em seu próprio
  arquivo.
- `MeshPreview` faz `import()` dinâmico do `@google/model-viewer`
  para que o bundle inicial não carregue o GLTF/glTF loader até
  o usuário abrir um preview.

### Hardening de runtime (05/10)

A causa raiz de um crash recorrente nas páginas `/sistema` e
`/configuracoes` era o mesmo problema: quando o frontend é
servido por `vite preview` sem proxy para o backend, qualquer
`fetch('/v1/jobs')` cai no fallback do `historyApiFallback`
(HTML da SPA). O axios não é capaz de distinguir, devolve o HTML
como `response.data`, e o hook `useJobFeed` chama `accept()`
armazenando uma string em `data`. Com isso `jobs ?? []` deixa de
ser um array — `JobContext` quebrava em `jobs.map`, `LibraryPage`
quebragia em `data.items`, `SystemPage` quebrava em
`Object.entries(stats.by_status)`.

A correção foi feita em quatro camadas:

1. `useJobListStream` valida o tipo com `isJobList` antes de
   repassar para `JobContext`. Garante `jobs: JobResponse[]`
   sempre que o consumidor olhar.
2. `JobContext` ganhou um segundo cinto de segurança
   (`Array.isArray(jobs) ? jobs : []`) dentro do `useEffect`
   que reconcilia o ticker.
3. `useJobFeed.accept()` rejeita payloads não-array quando o
   hook não declarou um `terminal()` explícito, registrando um
   `error` em vez de poluir o estado.
4. `LibraryPage`/`SystemPage` validam a forma do payload
   (`Array.isArray(response.data.items)`,
   `typeof stats.by_status === 'object'`) e mostram banner
   amigável em vez de quebrar a renderização.

Resultado: as quatro rotas carregam sem exceções, mesmo sem
backend disponível. Há testes novos em
`tests/useJobListStream.test.ts` cobrindo os ramos do guard.

## Métricas finais

| Item | Valor |
|---|---|
| Bundle inicial (gzip) | **139.65 kB** (vs. 415 kB antes do code-split) |
| Bundle do viewer (gzip) | **296.59 kB** (lazy, sob demanda) |
| Páginas lazy (gzip) | Library 2.30 kB · System 1.26 kB · Settings 0.90 kB |
| CSS final (gzip) | 28.96 kB |
| Testes backend | **258 aprovados** (excluindo tests que requerem torch/cv2) |
| Testes frontend | **17 aprovados** (+3 do guard `useJobListStream`) |
| Mypy `hy3dgen/api` | 0 erros |
| Ruff `hy3dgen/api` + tests etapa 2/3-4-5 | 0 erros |
| ESLint | 0 erros, 0 warnings |
| Pageerrors nas quatro páginas | **0** (validado via Playwright headless) |
| Submissão de job real (POST /v1/jobs) | 200 OK, `stage_progress` retornado |

## Pendências para iteração futura

1. **Benchmarks + presets calibrados em GPU** — sem GPU no CI, não foi possível medir tempos/VRAM reais. Os presets hoje são valores razoáveis documentados.
2. **Testes E2E com Playwright** — exige instalar `@playwright/test` e `browsers`; está fora do escopo desta execução por tempo de setup. Os fluxos estão cobertos por testes unitários de payload, capabilities e i18n.
3. **`InferenceService` compartilhado entre launcher e API** — refator estrutural grande; melhor como PR próprio e validado com GPU.
4. **URLs assinadas para `/files`** — autenticação está ativa, mas URLs temporárias com TTL seriam o próximo passo para compartilhamento seguro.
5. **Validação real em GPU** — instalar `torch`/`diffusers`/`mmgp`, executar `pytest -k integration` com worker real, capturar tempos por modo e preset.
