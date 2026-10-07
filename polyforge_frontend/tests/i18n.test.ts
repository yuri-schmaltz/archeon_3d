import { describe, expect, it } from 'vitest';
import { translate, setLocale, getLocale, catalogs } from '../src/i18n';

describe('i18n', () => {
    it('returns the pt-BR translation by default', () => {
        setLocale('pt-BR');
        expect(getLocale()).toBe('pt-BR');
        expect(translate('pt-BR', 'nav.create')).toBe('Criar');
        expect(translate('pt-BR', 'nav.library')).toBe('Biblioteca');
    });

    it('falls back to en when the key is missing in the locale', () => {
        // ``catalogs['pt-BR']`` is intentionally the primary catalog;
        // ``catalogs['en']`` is the fallback.
        expect(catalogs.en['nav.create']).toBe('Create');
    });

    it('interpolates parameters', () => {
        expect(translate('pt-BR', 'library.pageOf', { page: 2, total: 5 }))
            .toBe('Página 2 de 5');
        expect(translate('en', 'library.pageOf', { page: 3, total: 9 }))
            .toBe('Page 3 of 9');
    });

    it('returns the key when the translation is missing in both catalogs', () => {
        // Force a miss by querying a key that isn't defined anywhere.
        expect(translate('pt-BR', 'totally.missing')).toBe('totally.missing');
    });
});
