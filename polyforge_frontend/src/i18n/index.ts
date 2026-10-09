/**
 * Minimal i18n: a typed catalog + a tiny hook. No deps, no async loading.
 * Locale is persisted in localStorage; default is "pt-BR".
 */
import { useSyncExternalStore } from 'react';

export type Locale = 'pt-BR' | 'en';

export const LOCALES: Array<{ id: Locale; label: string }> = [
    { id: 'pt-BR', label: 'Português (Brasil)' },
    { id: 'en', label: 'English' },
];

type Catalog = Record<string, string>;

const catalogs: Record<Locale, Catalog> = {
    'pt-BR': {
        'app.title': 'PolyForge',
        'app.tagline': 'Do prompt ao polígono',
        'nav.create': 'Criar',
        'nav.library': 'Biblioteca',
        'nav.system': 'Sistema',
        'nav.settings': 'Ajustes',
        'header.live': 'Ao vivo',
        'header.refreshing': 'Atualizando',
        'header.connecting': 'Conectando',
        'header.studio': 'Estúdio local',
        'create.heading': 'Configurar geração',
        'create.heading.hint': 'Escolha um modo, preencha a entrada e gere um modelo 3D.',
        'create.mode.text': 'Texto',
        'create.mode.text.hint': 'Prompt → modelo',
        'create.mode.image': 'Imagem',
        'create.mode.image.hint': 'Imagem → modelo',
        'create.mode.multiview': '4 vistas',
        'create.mode.multiview.hint': 'Vistas → modelo',
        'create.mode.texture': 'Re-textura',
        'create.mode.texture.hint': 'Malha + referência',
        'create.field.prompt': 'Prompt',
        'create.field.prompt.hint': 'Descreva o que você quer gerar. Os primeiros 60 caracteres orientam a imagem de referência.',
        'create.field.texturePrompt': 'Prompt de textura',
        'create.field.texturePrompt.hint': 'Opcional se houver imagem de referência.',
        'create.field.image': 'Imagem de referência',
        'create.field.image.hint': 'PNG, JPEG ou WebP.',
        'create.field.front': 'Vista frontal',
        'create.field.back': 'Vista traseira',
        'create.field.left': 'Vista esquerda',
        'create.field.right': 'Vista direita',
        'create.field.mesh': 'Malha (GLB)',
        'create.field.refImage': 'Imagem de referência para textura',
        'create.advanced': 'Avançado',
        'create.preset.fast': 'Rápido',
        'create.preset.balanced': 'Equilibrado',
        'create.preset.detailed': 'Detalhado',
        'create.steps': 'Passos',
        'create.guidance': 'Orientação',
        'create.seed': 'Semente',
        'create.octree': 'Resolução do octree',
        'create.faceCount': 'Quantidade de faces',
        'create.texture': 'Gerar textura',
        'create.submit': 'Gerar modelo',
        'create.submit.busy': 'Enviando…',
        'create.banner.modelNotLoaded':
            'Modelo do backend ainda não carregado. Você pode configurar o job; o envio só vai funcionar quando o modelo estiver pronto. O ponto ao lado de cada modo indica a disponibilidade.',
        'create.error.unsupportedType': 'Tipo de imagem não suportado. Use PNG, JPEG ou WebP.',
        'create.error.imageTooLarge': 'Imagem muito grande. Máximo {max} MB.',
        'create.error.viewTooLarge': 'Vista "{view}" muito grande. Máximo {max} MB.',
        'create.error.viewType': 'Vista "{view}" precisa ser PNG, JPEG ou WebP.',
        'create.error.meshRequired': 'Selecione um arquivo GLB.',
        'create.error.meshTooLarge': 'Malha muito grande. Máximo {max} MB.',
        'create.error.referenceRequired': 'Selecione uma malha e uma imagem de referência ou prompt.',
        'create.success.submitted': 'Trabalho enviado.',
        'create.success.submittedWith': 'Trabalho enviado como {mode}.',
        'library.heading': 'Biblioteca',
        'library.heading.hint': 'Histórico paginado de gerações. Busque, abra o detalhe e reutilize parâmetros.',
        'library.search': 'Buscar por prompt, UID ou tipo',
        'library.filter.all': 'Todos',
        'library.filter.queued': 'Na fila',
        'library.filter.processing': 'Processando',
        'library.filter.completed': 'Concluídos',
        'library.filter.failed': 'Falhados',
        'library.filter.cancelled': 'Cancelados',
        'library.empty.title': 'Nenhum trabalho ainda',
        'library.empty.body': 'Seu primeiro prompt criará um arquivo .glb em minutos. As gerações ficarão arquivadas aqui, com busca, filtros e reutilização de parâmetros.',
        'library.empty.cta': '+ Criar meu primeiro trabalho',
        'library.detail': 'Detalhe',
        'library.reuse': 'Reutilizar parâmetros',
        'library.optimize': 'Otimizar',
        'library.cancel': 'Cancelar',
        'library.download': 'Baixar',
        'library.preview': 'Pré-visualizar',
        'library.preview.close': 'Fechar pré-visualização',
        'library.error': 'Falha',
        'library.separate': 'Separar peças',
        'library.separate.busy': 'Separando…',
        'library.separate.done': 'Peças separadas em {count} partes',
        'library.separate.empty': 'Nenhuma peça detectada',
        'library.parts': 'Peças ({count})',
        'library.parts.faces': '{count} faces',
        'library.next': 'Próxima',
        'library.prev': 'Anterior',
        'library.pageOf': 'Página {page} de {total}',
        'system.heading': 'Sistema',
        'system.heading.hint': 'Estado operacional do servidor e da fila.',
        'system.metrics': 'Métricas',
        'system.queue': 'Fila',
        'system.persistence': 'Persistência',
        'system.models': 'Modelos',
        'system.unlimited': 'Sem limite',
        'settings.heading': 'Ajustes',
        'settings.heading.hint': 'Idioma, atalhos e identificadores locais.',
        'settings.language': 'Idioma',
        'settings.version': 'Versão',
        'settings.server': 'Servidor',
        'settings.shortcuts': 'Atalhos',
        'settings.shortcuts.create': 'Ir para Criar',
        'settings.shortcuts.library': 'Ir para Biblioteca',
        'settings.shortcuts.system': 'Ir para Sistema',
        'settings.shortcuts.settings': 'Ir para Ajustes',
        'common.cancel': 'Cancelar',
        'common.retry': 'Tentar novamente',
        'common.refresh': 'Atualizar',
        'common.back': 'Voltar',
        'common.close': 'Fechar',
        'stage.loading_model': 'Carregando modelo',
        'stage.shape_generation': 'Gerando geometria',
        'stage.texturing': 'Texturizando',
        'stage.exporting': 'Exportando',
        'stage.unknown': 'Processando',
        // Viewer controls
        'viewer.textured': 'Texturizado',
        'viewer.geometry': 'Geometria',
        'viewer.wireframe': 'Wireframe',
        'viewer.env.neutral': 'Neutro',
        'viewer.env.studio': 'Estúdio',
        'viewer.env.outdoor': 'Exterior',
        'viewer.bg.transparent': 'Transparente',
        'viewer.bg.dark': 'Escuro',
        'viewer.bg.gradient': 'Gradiente',
        'viewer.resetCamera': 'Resetar câmera',
        'viewer.ar': 'Ver em AR',
        'viewer.loading': 'Carregando visualizador…',
        'viewer.downloadInstead': 'Baixar ao invés',
        // Auth gate
        'auth.connecting': 'Conectando ao servidor de geração…',
        'auth.offline.title': 'Servidor de geração indisponível',
        'auth.offline.body': 'Verifique se o backend está em execução. Você pode tentar reconectar abaixo.',
        'auth.reconnect': 'Reconectar',
        'auth.locked.title': 'Esta instância requer uma chave de API',
        'auth.locked.body': 'Solicite a chave ao administrador do servidor. A credencial fica em memória apenas — não é gravada em disco.',
        'auth.field.label': 'Chave de API',
        'auth.submit.connect': 'Conectar',
        'auth.submit.connecting': 'Conectando…',
        'auth.error.invalid': 'Não foi possível conectar. Verifique a chave de API e tente novamente.',
        'auth.alert.connecting': 'Conectando…',
        'auth.alert.offline': 'Servidor indisponível',
        'auth.alert.locked': 'Autenticação necessária',
        // Capability strip
        'strip.status.ready': 'pronto',
        'strip.status.loading': 'carregando',
        'strip.status.offline': 'offline',
        'strip.status.error': 'erro',
        'strip.field.mode': 'modo',
        'strip.field.model': 'modelo',
        'strip.field.queue': 'fila',
        'strip.field.texture': 'textura',
        'strip.field.gpu': 'gpu',
    },
    en: {
        'app.title': 'PolyForge',
        'app.tagline': 'From prompt to polygon',
        'nav.create': 'Create',
        'nav.library': 'Library',
        'nav.system': 'System',
        'nav.settings': 'Settings',
        'header.live': 'Live',
        'header.refreshing': 'Refreshing',
        'header.connecting': 'Connecting',
        'header.studio': 'Local studio',
        'create.heading': 'Configure generation',
        'create.heading.hint': 'Pick a mode, fill the input, then generate a 3D model.',
        'create.mode.text': 'Text',
        'create.mode.text.hint': 'Prompt → mesh',
        'create.mode.image': 'Image',
        'create.mode.image.hint': 'Image → mesh',
        'create.mode.multiview': '4 views',
        'create.mode.multiview.hint': 'Views → mesh',
        'create.mode.texture': 'Re-texture',
        'create.mode.texture.hint': 'Mesh + reference',
        'create.field.prompt': 'Prompt',
        'create.field.prompt.hint': 'Describe what you want to generate. The first 60 characters guide the reference image.',
        'create.field.texturePrompt': 'Texture prompt',
        'create.field.texturePrompt.hint': 'Optional when a reference image is provided.',
        'create.field.image': 'Reference image',
        'create.field.image.hint': 'PNG, JPEG or WebP.',
        'create.field.front': 'Front view',
        'create.field.back': 'Back view',
        'create.field.left': 'Left view',
        'create.field.right': 'Right view',
        'create.field.mesh': 'Mesh (GLB)',
        'create.field.refImage': 'Reference image for texture',
        'create.advanced': 'Advanced',
        'create.preset.fast': 'Fast',
        'create.preset.balanced': 'Balanced',
        'create.preset.detailed': 'Detailed',
        'create.steps': 'Steps',
        'create.guidance': 'Guidance',
        'create.seed': 'Seed',
        'create.octree': 'Octree resolution',
        'create.faceCount': 'Face count',
        'create.texture': 'Generate texture',
        'create.submit': 'Generate model',
        'create.submit.busy': 'Submitting…',
        'create.banner.modelNotLoaded':
            'Backend model is not loaded yet. You can configure the job; submission will only succeed once the model is ready. The dot next to each mode indicates availability.',
        'create.error.unsupportedType': 'Unsupported image type. Use PNG, JPEG or WebP.',
        'create.error.imageTooLarge': 'Image too large. Max {max} MB.',
        'create.error.viewTooLarge': 'View "{view}" too large. Max {max} MB.',
        'create.error.viewType': 'View "{view}" must be PNG, JPEG or WebP.',
        'create.error.meshRequired': 'Select a GLB file.',
        'create.error.meshTooLarge': 'Mesh too large. Max {max} MB.',
        'create.error.referenceRequired': 'Pick a mesh and a reference image or prompt.',
        'create.success.submitted': 'Job submitted.',
        'create.success.submittedWith': 'Job submitted as {mode}.',
        'library.heading': 'Library',
        'library.heading.hint': 'Paginated history. Search, open detail, and reuse parameters.',
        'library.search': 'Search by prompt, UID or type',
        'library.filter.all': 'All',
        'library.filter.queued': 'Queued',
        'library.filter.processing': 'Processing',
        'library.filter.completed': 'Completed',
        'library.filter.failed': 'Failed',
        'library.filter.cancelled': 'Cancelled',
        'library.empty.title': 'No jobs yet',
        'library.empty.body': 'Your first prompt will create a .glb file in minutes. All generations will be archived here with search, filters and parameter reuse.',
        'library.empty.cta': '+ Create my first job',
        'library.detail': 'Detail',
        'library.reuse': 'Reuse parameters',
        'library.optimize': 'Optimize',
        'library.cancel': 'Cancel',
        'library.download': 'Download',
        'library.preview': 'Preview',
        'library.preview.close': 'Close preview',
        'library.error': 'Failed',
        'library.separate': 'Separate parts',
        'library.separate.busy': 'Separating…',
        'library.separate.done': 'Separated into {count} parts',
        'library.separate.empty': 'No parts detected',
        'library.parts': 'Parts ({count})',
        'library.parts.faces': '{count} faces',
        'library.next': 'Next',
        'library.prev': 'Prev',
        'library.pageOf': 'Page {page} of {total}',
        'system.heading': 'System',
        'system.heading.hint': 'Server operational state and queue.',
        'system.metrics': 'Metrics',
        'system.queue': 'Queue',
        'system.persistence': 'Persistence',
        'system.models': 'Models',
        'system.unlimited': 'Unlimited',
        'settings.heading': 'Settings',
        'settings.heading.hint': 'Language, shortcuts, and local identifiers.',
        'settings.language': 'Language',
        'settings.version': 'Version',
        'settings.server': 'Server',
        'settings.shortcuts': 'Shortcuts',
        'settings.shortcuts.create': 'Go to Create',
        'settings.shortcuts.library': 'Go to Library',
        'settings.shortcuts.system': 'Go to System',
        'settings.shortcuts.settings': 'Go to Settings',
        'common.cancel': 'Cancel',
        'common.retry': 'Retry',
        'common.refresh': 'Refresh',
        'common.back': 'Back',
        'common.close': 'Close',
        'stage.loading_model': 'Loading model',
        'stage.shape_generation': 'Generating shape',
        'stage.texturing': 'Texturing',
        'stage.exporting': 'Exporting',
        'stage.unknown': 'Processing',
        // Viewer controls
        'viewer.textured': 'Textured',
        'viewer.geometry': 'Geometry',
        'viewer.wireframe': 'Wireframe',
        'viewer.env.neutral': 'Neutral',
        'viewer.env.studio': 'Studio',
        'viewer.env.outdoor': 'Outdoor',
        'viewer.bg.transparent': 'Transparent',
        'viewer.bg.dark': 'Dark',
        'viewer.bg.gradient': 'Gradient',
        'viewer.resetCamera': 'Reset camera',
        'viewer.ar': 'View in AR',
        'viewer.loading': 'Loading viewer…',
        'viewer.downloadInstead': 'Download instead',
        // Auth gate
        'auth.connecting': 'Connecting to the generation server…',
        'auth.offline.title': 'Generation server unavailable',
        'auth.offline.body': 'Check that the backend is running. You can retry the connection below.',
        'auth.reconnect': 'Reconnect',
        'auth.locked.title': 'This instance requires an API key',
        'auth.locked.body': 'Ask the server administrator for the key. The credential stays in memory only — it is never written to disk.',
        'auth.field.label': 'API key',
        'auth.submit.connect': 'Connect',
        'auth.submit.connecting': 'Connecting…',
        'auth.error.invalid': 'Could not connect. Check the API key and try again.',
        'auth.alert.connecting': 'Connecting',
        'auth.alert.offline': 'Server offline',
        'auth.alert.locked': 'Authentication required',
        // Capability strip
        'strip.status.ready': 'ready',
        'strip.status.loading': 'loading',
        'strip.status.offline': 'offline',
        'strip.status.error': 'error',
        'strip.field.mode': 'mode',
        'strip.field.model': 'model',
        'strip.field.queue': 'queue',
        'strip.field.texture': 'texture',
        'strip.field.gpu': 'gpu',
    },
};

const STORAGE_KEY = 'polyforge.locale';
const DEFAULT_LOCALE: Locale = 'pt-BR';

function readStoredLocale(): Locale {
    if (typeof window === 'undefined') return DEFAULT_LOCALE;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'pt-BR' || raw === 'en') return raw;
    return DEFAULT_LOCALE;
}

const listeners = new Set<() => void>();
function subscribe(cb: () => void): () => void {
    listeners.add(cb);
    return () => listeners.delete(cb);
}

let currentLocale: Locale = readStoredLocale();
export function getLocale(): Locale {
    return currentLocale;
}

export function setLocale(locale: Locale): void {
    if (currentLocale === locale) return;
    currentLocale = locale;
    if (typeof window !== 'undefined') {
        window.localStorage.setItem(STORAGE_KEY, locale);
        document.documentElement.lang = locale;
    }
    listeners.forEach((cb) => cb());
}

export function useLocale(): Locale {
    return useSyncExternalStore(subscribe, getLocale, getLocale);
}

/** Resolve a key with placeholder substitution: ``t('key', { max: 10 })``. */
export function translate(locale: Locale, key: string, params?: Record<string, string | number>): string {
    const catalog = catalogs[locale];
    const fallback = catalogs['en'] ?? catalogs['pt-BR'];
    let value = catalog[key] ?? fallback[key] ?? key;
    if (params) {
        for (const [name, replacement] of Object.entries(params)) {
            value = value.replaceAll(`{${name}}`, String(replacement));
        }
    }
    return value;
}

/** React hook returning the translator function for the current locale. */
export function useT(): (key: string, params?: Record<string, string | number>) => string {
    const locale = useLocale();
    return (key, params) => translate(locale, key, params);
}

/** Stage label lookup; returns the localized stage or "unknown" by default. */
export function stageLabel(locale: Locale, stage: string | null | undefined): string {
    if (!stage) return translate(locale, 'stage.unknown');
    const key = `stage.${stage}`;
    return translate(locale, key);
}

export { catalogs };
