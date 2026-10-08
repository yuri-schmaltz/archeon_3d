# Implementação inicial — estabilização e base de UI/UX

Data: 04/10/2026. Referência: [diagnóstico e plano de ação](PLANO_DE_MELHORIAS_2026-10-04.md).

Foi implementado o primeiro bloco funcional do plano, com antecipação de melhorias
necessárias de operação e responsividade. O aceite completo da etapa 1 depende
principalmente da inferência real em GPU e do build do backend CUDA; o roadmap
inteiro não está concluído.

## Mudanças entregues

### API, fila e persistência

- Rotas aguardam cancelamento e inscrição SSE. O stream individual encerra ao
  receber estado terminal; trabalhos em processamento retornam 409 ao cancelar.
- A fila contabiliza cada item uma vez e drena trabalhos pendentes no shutdown.
  Limpeza de histórico é aguardada; device, modelos, diretório e retenção configurados
  são encaminhados ao manager.
- Eventos individuais recebem cópias do estado, preservando cada transição.
- Datas novas usam UTC com timezone; datas antigas sem offset são interpretadas
  como UTC. A retenção SQLite aceita timestamps com offsets.
- SQLite migra bases existentes para guardar `updated_at` e `request_type`,
  preservando o payload usado na retomada após reinício.
- Métricas incluem histórico em memória/banco e persistência; a medição de CPU
  reutiliza o processo para manter a referência entre amostras.
- Pós-processamento grava derivados no diretório servido por `/files`, preservando
  o original; simplificação usa a API atual do Trimesh e `fast-simplification`.

### Entrada e inferência

- O formulário monta somente o payload do modo selecionado. Texto de geração e
  referência textual de textura têm rascunhos separados.
- Multiview encaminha exatamente quatro vistas ao checkpoint configurado e mantém
  a opção de textura. A geometria solicita saída `trimesh`, aceita pelo pipeline.
- API inicia sem importar Torch. Geometria, texto para imagem, remoção de fundo
  e textura carregam por demanda; troca de modo libera o pipeline de geometria
  anterior. A opção de não remover o fundo é respeitada.
- Instalar somente a API permite operação/testes de serviço, mas não inferência.
  Perfis de offload do launcher ainda não foram integrados à API.

### Frontend e UI/UX

- Uma fonte de estado alimenta a galeria, com uma conexão SSE de lista. HTTP e SSE
  usam `X-API-Key`; a chave é informada na tela e fica somente em memória.
- Quedas de SSE ativam polling e reconexão com backoff. SSE saudável interrompe
  polling; Atualizar força uma leitura HTTP. Endpoints SSE ausentes usam polling.
- Estado de conexão, erros da API e erro do trabalho ficam visíveis; ações em
  andamento são desabilitadas. Cancelamento fica disponível para trabalhos na fila.
- Layout reorganiza o monitor de sistema em painel recolhível no mobile, sem
  manter duas instâncias consultando métricas. Galeria e ações se adaptam à largura.
- Títulos semânticos, contraste de texto, foco visível, alvos principais de toque
  e navegação das abas por setas/Home/End foram melhorados.
- “New model” leva ao formulário; “Documentation” abre a documentação da API.
- Limites no formulário: 10 MiB por imagem e 30 MiB por GLB. A API agora aplica
  limites de corpo e valida os tamanhos base64 no servidor.

### Instalação e operação

- Versão Python válida: `2.1.0.post7`; metadados centralizados no `pyproject.toml`.
  Wheel/sdist incluem módulos de modelos, launcher e fontes de extensões nativas.
- Compilação CUDA/C++ é explícita: `POLYFORGE_BUILD_NATIVE=1` com
  `--no-build-isolation`, ou `make install-native` após instalar o stack ML.
- Launcher local detecta modo de inferência, instala backend/frontend e serve
  a UI compilada pela mesma API. Frontend usa Node 22.
- Dependências npm atualizadas dentro dos intervalos compatíveis; CI inclui Vitest,
  Node 22 e elimina caminhos duplicados na chamada de mypy.
- READMEs e exemplos de ambiente atualizados, sem variável `VITE_*` para chave.

## Evidências de validação

| Verificação | Resultado |
| --- | --- |
| Suíte principal de backend, `TZ=America/Sao_Paulo` | **229 aprovados**, 178 warnings de testes existentes |
| Regressões novas no backend | 12 cenários: rotas, autenticação, fila, shutdown, retenção, migração, eventos, configuração e dispatch |
| Mypy em `hy3dgen/api` | Sem erros nos 10 módulos |
| Ruff check e format nos módulos Python alterados | Aprovados |
| Frontend ESLint, TypeScript e build | Aprovados |
| Vitest | **5 aprovados**, incluindo troca de modo e entradas incompletas |
| `npm audit` | **0 vulnerabilidades reportadas** na resolução atual |
| Build Python isolado | Wheel e sdist aprovados |
| Wheel instalado em ambiente sem Torch | API inicializa sem carregar ML; módulos/fontes necessários presentes |
| Instalação suportada | Launcher local; verificações Docker/proxy abaixo são apenas históricas |
| Chromium: formulário e galeria | Chave incorreta/correta, SSE com header, modo isolado, otimização e download GLB aprovados; sem exceções de página |
| Chromium: conectividade | Reconexão após queda de rede e polling autenticado quando SSE retorna 404 aprovados |
| Chromium: layout | Sem overflow de documento/conteúdo principal em **360, 390, 768 e 1440 px** |
| Chromium: SSE saudável | Zero consultas recorrentes de `/v1/jobs` durante a janela observada de 3,5 s |
| Chromium: teclado | Alternância de aba por seta preserva rascunho do modo anterior |

Os testes do navegador usaram a API, fila, SQLite, autenticação e SSE reais com um
worker controlado que exporta uma malha GLB válida. O teste de multiview verifica
os argumentos do pipeline e a exportação real, substituindo os modelos por stubs.
Esses testes **não comprovam geração de qualidade pelos modelos Hunyuan**.
O viewer externo foi bloqueado no teste do navegador; sua renderização 3D não foi
validada. Os resultados de smoke Docker/Nginx abaixo pertencem ao snapshot
histórico da Etapa 1 e não são parte da instalação local atual.

A suíte principal exclui os testes de imports/texgen/text2image e os grupos de
memória, concorrência, estresse SSE e retenção sob carga. Não representa execução
de toda a matriz ML/hardware. Ambiente: Python 3.12.3, FastAPI 0.142.2,
Pydantic 2.13.5, Trimesh 5.1.1 e Node 22.23.2.

Screenshots após a implementação:

- [Desktop](etapa-1/desktop.png)
- [Mobile](etapa-1/mobile.png)

Os screenshots do [diagnóstico](audit-2026-10-04/) continuam preservados para comparação.

## Pendências e próximo bloco

1. **Fechar o aceite em GPU:** construir a imagem CUDA com as extensões e testar
   texto, imagem, quatro vistas e retexturização com os modelos reais; registrar
   tempo, VRAM e download de cada resultado. Build do backend CUDA e compatibilidade
   do stack ML não foram validados nesta entrega.
2. **Completar os contratos:** tipos gerados de OpenAPI, capabilities verificáveis,
   progresso por etapa, URLs de artefatos e limites de fila/upload no servidor.
3. **Fechar a dívida do CI:** permanecem erros de lint/tipagem em outras áreas,
   inclusive código upstream. O CI completo não foi declarado aprovado; preservar
   visibilidade das falhas e tratá-las em mudança específica.
4. **Evoluir o ambiente de criação:** viewer local com carregamento/erro, biblioteca
   paginada, miniaturas, busca, detalhes, reutilização de parâmetros e exportação.
5. **Validar UX ampliada:** leitor de tela, zoom, redução de movimento, erros
   associados aos campos, português e testes de uso. Reautenticação atualmente
   remonta a aplicação e pode perder o rascunho; melhorar preservação nessa situação.
6. **Operação e eficiência:** offload compartilhado, retenção separada para banco/
   memória/arquivos, proteção de downloads conforme acesso e buffers SSE limitados.
   Inferência em execução continua sem cancelamento seguro.

As alterações são locais, sem commit, publicação ou implantação em produção.
