import React, { useEffect, useState } from 'react';
import { apiClient, BASE_URL, authHeaders } from '../api/client';
import { LOCALES as RAW_LOCALES, setLocale, useLocale, useT } from '../i18n';

// Defensive: if a code-split chunk loses access to the array constant,
// fall back to a local one rather than crashing the page.
const LOCALES_LIST: Array<{ id: 'pt-BR' | 'en'; label: string }> =
    (Array.isArray(RAW_LOCALES) && RAW_LOCALES.length > 0)
        ? RAW_LOCALES
        : [
              { id: 'pt-BR', label: 'Português (Brasil)' },
              { id: 'en', label: 'English' },
          ];
import {
    Text,
    Stack,
    Divider,
    Pill,
    Button,
} from '../design/primitives';

interface CapabilitiesLite {
    version: string;
}

const SHORTCUTS = [
    { combo: 'g c', i18n: 'settings.shortcuts.create', route: 'create' as const },
    { combo: 'g b', i18n: 'settings.shortcuts.library', route: 'library' as const },
    { combo: 'g s', i18n: 'settings.shortcuts.system', route: 'system' as const },
    { combo: 'g a', i18n: 'settings.shortcuts.settings', route: 'settings' as const },
];

export const SettingsPage: React.FC = () => {
    const t = useT();
    const locale = useLocale();
    const [capabilities, setCapabilities] = useState<CapabilitiesLite | null>(null);

    useEffect(() => {
        apiClient
            .get<CapabilitiesLite>('/capabilities', { headers: authHeaders() })
            .then((response) => setCapabilities(response.data))
            .catch(() => undefined);
    }, []);

    return (
        <section className="space-y-6">
            <header className="space-y-1">
                <Text as="h1" voice="display" size="xl" tracking="tight">
                    {t('settings.heading')}
                </Text>
                <Text voice="body" size="sm" tone="muted">
                    {t('settings.heading.hint')}
                </Text>
            </header>

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('settings.language')}
                </Text>
                <div className="flex flex-wrap gap-2">
                    {LOCALES_LIST.map((entry) => (
                        <Button
                            key={entry.id}
                            variant={entry.id === locale ? 'primary' : 'secondary'}
                            size="sm"
                            onClick={() => setLocale(entry.id)}
                        >
                            {entry.label}
                        </Button>
                    ))}
                </div>
            </Stack>

            <Divider />

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('settings.server')}
                </Text>
                <ul className="space-y-2 text-sm">
                    <Row label={t('settings.version')} value={capabilities?.version ?? '—'} />
                    <Row label="URL" value={BASE_URL} />
                </ul>
            </Stack>

            <Divider />

            <Stack gap={3}>
                <Text voice="mono" size="2xs" tone="muted" tracking="widest" uppercase>
                    {t('settings.shortcuts')}
                </Text>
                <ul className="grid gap-2 sm:grid-cols-2">
                    {SHORTCUTS.map((shortcut) => (
                        <li key={shortcut.combo} className="flex items-center justify-between gap-2 border border-border rounded p-2">
                            <Pill tone="accent">{shortcut.combo}</Pill>
                            <Text voice="body" size="sm">
                                {t(shortcut.i18n)}
                            </Text>
                        </li>
                    ))}
                </ul>
            </Stack>
        </section>
    );
};

const Row: React.FC<{ label: string; value: string }> = ({ label, value }) => (
    <li className="flex justify-between border-b border-border py-1">
        <Text voice="mono" size="2xs" tone="muted" tracking="wider" uppercase>
            {label}
        </Text>
        <Text voice="mono" size="sm" tone="fg" className="tabular-nums">
            {value}
        </Text>
    </li>
);

export default SettingsPage;
