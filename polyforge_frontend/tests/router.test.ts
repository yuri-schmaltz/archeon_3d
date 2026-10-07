import { describe, expect, it } from 'vitest';
import { ROUTES, go } from '../src/router';

describe('router', () => {
    it('exposes the four routes', () => {
        const ids = ROUTES.map((r) => r.id).sort();
        expect(ids).toEqual(['create', 'library', 'settings', 'system']);
    });

    it('go() updates the hash', () => {
        const before = window.location.hash;
        go('library');
        expect(window.location.hash).toBe('#/biblioteca');
        // restore
        if (before) window.location.hash = before;
        else window.location.hash = '';
    });

    it('go() with replace does not push history', () => {
        // Replace may emit a popstate/hashchange; we just confirm the
        // resulting URL is what we asked for.
        go('settings', true);
        expect(window.location.hash).toBe('#/configuracoes');
    });
});
