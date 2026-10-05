import type { BaseGenerationRequest } from './types';

export type GenerationMode = 'text' | 'image' | 'multiview' | 'texture';
export type ViewKey = 'front' | 'back' | 'left' | 'right';
export const VIEW_KEYS: ViewKey[] = ['front', 'back', 'left', 'right'];
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const MAX_MESH_BYTES = 30 * 1024 * 1024;

export interface GenerationInputs {
    text: string;
    texturePrompt: string;
    image: File | null;
    views: Record<ViewKey, File | null>;
    mesh: File | null;
    refImage: File | null;
}
export interface GenerationRequest extends BaseGenerationRequest {
    text?: string;
    image?: string;
    views?: Record<ViewKey, string>;
    mesh?: string;
}

export async function buildGenerationRequest(mode: GenerationMode, inputs: GenerationInputs,
    parameters: BaseGenerationRequest, encode = fileToBase64): Promise<GenerationRequest> {
    const payload: GenerationRequest = { ...parameters };
    if (mode === 'text') {
        if (!inputs.text.trim()) throw new Error('Enter a prompt.');
        payload.text = inputs.text.trim();
    } else if (mode === 'image') {
        if (!inputs.image) throw new Error('Choose a source image.');
        payload.image = await encode(inputs.image);
    } else if (mode === 'multiview') {
        if (!VIEW_KEYS.every((key) => inputs.views[key])) throw new Error('Choose all four views.');
        const encoded = await Promise.all(VIEW_KEYS.map(async (key) => [key, await encode(inputs.views[key]!)]));
        payload.views = Object.fromEntries(encoded) as Record<ViewKey, string>;
    } else {
        if (!inputs.mesh || (!inputs.refImage && !inputs.texturePrompt.trim())) {
            throw new Error('Choose a GLB and a reference image or prompt.');
        }
        payload.mesh = await encode(inputs.mesh);
        payload.texture = true;
        if (inputs.refImage) payload.image = await encode(inputs.refImage);
        if (inputs.texturePrompt.trim()) payload.text = inputs.texturePrompt.trim();
    }
    return payload;
}

function fileToBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => typeof reader.result === 'string'
            ? resolve(reader.result.slice(reader.result.indexOf(',') + 1))
            : reject(new Error('Could not read the file.'));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}
