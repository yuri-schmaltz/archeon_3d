/**
 * Tests for the new "separate parts" mesh-ops surface.
 *
 * These mirror the backend ``MeshOpsRequest`` schema so the frontend
 * stays in sync when fields are added/renamed. Anything the API can
 * accept must also be type-safe on this side; if a new field is
 * missing from the type below, the request would silently drop it.
 */
import { describe, it, expect } from 'vitest';
import type {
    MeshOpsAction,
    MeshOpsRequest,
    MeshOpsResponse,
    MeshPartInfo,
} from '../src/api/types';

describe('MeshOpsAction union', () => {
    it('contains the three actions the backend exposes', () => {
        const actions: MeshOpsAction[] = ['decimate', 'convert', 'separate'];
        // Type assertion: the array is the exhaustive list and all
        // members are valid MeshOpsAction values.
        for (const action of actions) {
            const probe: MeshOpsAction = action;
            expect(probe).toBe(action);
        }
    });

    it('includes "separate" as a literal', () => {
        const action: MeshOpsAction = 'separate';
        expect(action).toBe('separate');
    });
});

describe('MeshOpsRequest with action="separate"', () => {
    it('accepts the minimal payload', () => {
        const req: MeshOpsRequest = {
            job_uid: 'job-1',
            action: 'separate',
        };
        expect(req.action).toBe('separate');
        expect(req.job_uid).toBe('job-1');
    });

    it('forwards every tuneable the backend understands', () => {
        // The backend schema defines: min_face_count, only_watertight,
        // repair, min_volume_ratio. If a future PR renames or removes
        // one of these, the test below breaks loudly.
        const req: MeshOpsRequest = {
            job_uid: 'job-1',
            action: 'separate',
            format: 'glb',
            min_face_count: 500,
            only_watertight: false,
            repair: true,
            min_volume_ratio: 0.0,
        };
        expect(req.min_face_count).toBe(500);
        expect(req.only_watertight).toBe(false);
        expect(req.repair).toBe(true);
        expect(req.min_volume_ratio).toBe(0.0);
    });
});

describe('MeshOpsResponse shape for action="separate"', () => {
    it('exposes a parts inventory with name + face/vertex counts', () => {
        const part: MeshPartInfo = {
            name: 'part_000_1200f',
            face_count: 1200,
            vertex_count: 800,
        };
        const response: MeshOpsResponse = {
            file_path: '/tmp/job.glb',
            parts: [part, { ...part, name: 'part_001_400f', face_count: 400, vertex_count: 250 }],
        };
        expect(response.file_path).toBeTruthy();
        expect(response.parts).toHaveLength(2);
        expect(response.parts?.[0].face_count).toBe(1200);
        expect(response.parts?.[0].vertex_count).toBe(800);
    });

    it('keeps parts optional for non-separate actions', () => {
        const response: MeshOpsResponse = { file_path: '/tmp/x.glb' };
        expect(response.parts).toBeUndefined();
    });
});