import React from 'react';
import { Text, Divider, Button, Stack } from "../design/primitives";
import { SystemMonitor } from "./monitoring/SystemMonitor";
import { BASE_URL } from "../api/client";
import { ROUTES, useRoute, go } from '../router';
import { useT } from '../i18n';
import { clsx } from 'clsx';

export const LeftRail: React.FC = () => {
    const t = useT();
    const current = useRoute();
    return (
        <aside className="hidden lg:flex w-64 shrink-0 border-r border-border bg-bg flex-col overflow-y-auto">
            <nav aria-label="Primary" className="px-3 py-3">
                <Stack gap={1}>
                    {ROUTES.map((route) => {
                        const active = route.id === current;
                        return (
                            <button
                                key={route.id}
                                type="button"
                                onClick={() => go(route.id)}
                                aria-current={active ? 'page' : undefined}
                                className={clsx(
                                    'flex items-center gap-3 px-3 h-9 text-left rounded-sm',
                                    'focus:outline-none focus-visible:ring-1 focus-visible:ring-accent',
                                    active
                                        ? 'bg-surface-2 text-fg'
                                        : 'text-fg-muted hover:text-fg hover:bg-surface-1',
                                )}
                            >
                                <span aria-hidden="true" className="text-sm w-4 text-center">
                                    {route.glyph}
                                </span>
                                <span className="font-mono text-xs uppercase tracking-wider">
                                    {t(`nav.${route.id}`)}
                                </span>
                                {active && (
                                    <span
                                        aria-hidden="true"
                                        className="ml-auto h-1.5 w-1.5 rounded-full bg-accent"
                                    />
                                )}
                            </button>
                        );
                    })}
                </Stack>
            </nav>
            <Divider />
            <div className="px-5 py-4">
                <Stack gap={2}>
                    <Text
                        voice="mono"
                        size="2xs"
                        tone="muted"
                        tracking="widest"
                        uppercase
                    >
                        {t('system.metrics')}
                    </Text>
                </Stack>
            </div>
            <Divider />
            <div className="px-5 py-4">
                <SystemMonitor />
            </div>
            <div className="flex-1" />
            <Divider />
            <div className="px-5 py-4">
                <Stack gap={2}>
                    <Text
                        voice="mono"
                        size="2xs"
                        tone="muted"
                        tracking="widest"
                        uppercase
                    >
                        {t('settings.server')}
                    </Text>
                    <a href={`${BASE_URL}/docs`} target="_blank" rel="noreferrer"
                        className="text-sm text-fg-muted hover:text-fg py-2">API →</a>
                    <a href={`${BASE_URL}/openapi.json`} target="_blank" rel="noreferrer"
                        className="text-sm text-fg-muted hover:text-fg py-2">OpenAPI →</a>
                    <Button variant="secondary" size="sm" block onClick={() => {
                        const form = document.getElementById("create-job");
                        form?.scrollIntoView({ block: "start" });
                        form?.querySelector<HTMLElement>("textarea, input")?.focus();
                    }}>
                        + {t('nav.create')}
                    </Button>
                </Stack>
            </div>
        </aside>
    );
};
