import { useEffect } from 'react';
import { useEnsureDefaultRoute, go } from '../router';

// "g c" / "g b" / "g s" / "g a" navigation. Ignored when typing in inputs.
export function KeyboardShortcuts(): null {
    useEnsureDefaultRoute();
    useEffect(() => {
        let prefix = false;
        const handler = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return;
            }
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            if (!prefix) {
                if (event.key === 'g') {
                    prefix = true;
                    setTimeout(() => (prefix = false), 1000);
                }
                return;
            }
            prefix = false;
            switch (event.key) {
                case 'c': go('create'); break;
                case 'b': go('library'); break;
                case 's': go('system'); break;
                case 'a': go('settings'); break;
                default: break;
            }
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, []);
    return null;
}
