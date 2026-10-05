import { describe, it, expect, vi } from 'vitest';
import { buildGenerationRequest, type GenerationInputs } from '../src/api/generation';

const file = (name: string) => ({ name }) as File;
const inputs: GenerationInputs = {
    text: 'old prompt', texturePrompt: 'wood finish', image: file('source.png'),
    mesh: file('mesh.glb'), refImage: file('ref.png'),
    views: { front: file('front.png'), back: file('back.png'), left: file('left.png'), right: file('right.png') },
};
const settings = { steps: 50, guidance: 5, seed: 1, texture: false };
const encode = vi.fn(async (value: File) => `base64:${value.name}`);

describe('generation inputs are isolated by selected mode', () => {
    it('sends only the source image after leaving other tabs populated', async () => {
        encode.mockClear();
        const payload = await buildGenerationRequest('image', inputs, settings, encode);
        expect(payload).toEqual({ ...settings, image: 'base64:source.png' });
        expect(encode).toHaveBeenCalledTimes(1);
    });
    it('does not send hidden files for a text request', async () => {
        encode.mockClear();
        expect(await buildGenerationRequest('text', inputs, settings, encode)).toEqual({ ...settings, text: 'old prompt' });
        expect(encode).not.toHaveBeenCalled();
    });
    it('sends exactly four views for multiview', async () => {
        const payload = await buildGenerationRequest('multiview', inputs, settings, encode);
        expect(payload).toEqual({ ...settings, views: { front: 'base64:front.png', back: 'base64:back.png', left: 'base64:left.png', right: 'base64:right.png' } });
    });
    it('uses the separate texture prompt and reference image', async () => {
        const payload = await buildGenerationRequest('texture', inputs, settings, encode);
        expect(payload).toEqual({ ...settings, texture: true, text: 'wood finish', mesh: 'base64:mesh.glb', image: 'base64:ref.png' });
    });
    it('rejects incomplete views and references before submitting', async () => {
        await expect(buildGenerationRequest('multiview', { ...inputs, views: { ...inputs.views, right: null } }, settings, encode)).rejects.toThrow('four views');
        await expect(buildGenerationRequest('texture', { ...inputs, texturePrompt: ' ', refImage: null }, settings, encode)).rejects.toThrow('reference');
    });
});
