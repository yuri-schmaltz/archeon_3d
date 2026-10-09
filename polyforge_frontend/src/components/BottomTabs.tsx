import React from 'react';
import { ROUTES, useRoute, go } from '../router';
import { useT } from '../i18n';
import { clsx } from 'clsx';

export const BottomTabs: React.FC = () => {
    const t = useT();
    const current = useRoute();
    return (
        <nav
            aria-label="Primary"
            className="fixed bottom-0 left-0 right-0 z-40 bg-bg/95 backdrop-blur-sm border-t border-border h-14 flex items-stretch lg:hidden"
        >
            {ROUTES.map((route) => {
                const active = route.id === current;
                return (
                    <button
                        key={route.id}
                        type="button"
                        onClick={() => go(route.id)}
                        aria-current={active ? 'page' : undefined}
                        className={clsx(
                            'flex-1 min-w-0 flex flex-col items-center justify-center gap-0.5',
                            'focus-visible:text-accent',
                            active ? 'text-accent' : 'text-fg-muted hover:text-fg',
                        )}
                    >
                        <span aria-hidden="true" className="text-base leading-none">
                            {route.glyph}
                        </span>
                        <span className="font-mono text-2xs uppercase tracking-wider truncate px-1">
                            {t(`nav.${route.id}`)}
                        </span>
                    </button>
                );
            })}
        </nav>
    );
};
