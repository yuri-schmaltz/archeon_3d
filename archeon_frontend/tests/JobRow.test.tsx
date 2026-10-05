import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { JobRow } from '../src/components/library/JobRow';
import type { JobResponse, JobStatusType } from '../src/api/types';

const noopT = (key: string) => key;

function makeJob(error: string | null = null): JobResponse {
    return {
        uid: 'abcdef1234567890',
        status: 'failed' as JobStatusType,
        created_at: '2026-10-05T19:00:00.000Z',
        updated_at: '2026-10-05T19:00:01.000Z',
        completed_at: '2026-10-05T19:00:01.000Z',
        error,
        request_type: 'image_to_3d',
        file_path: null,
        stage: null,
        stage_progress: null,
    };
}

describe('JobRow error rendering', () => {
    it('renders a short error inline without a disclosure', () => {
        const onOpen = vi.fn();
        const onReuse = vi.fn();
        render(
            <JobRow
                job={makeJob('No module named diffusers')}
                statusKind="failed"
                onOpen={onOpen}
                onReuse={onReuse}
                t={noopT}
            />,
        );
        expect(screen.getByText(/no module named diffusers/i)).toBeTruthy();
        // No disclosure button when the error is short.
        expect(screen.queryByText(/mostrar detalhes/i)).toBeNull();
    });

    it('collapses a long multi-line error and shows first line + disclosure', () => {
        const longError = [
            'ModuleNotFoundError: No module named diffusers',
            'Traceback (most recent call last):',
            '  File "/foo/bar.py", line 12, in <module>',
            '    from diffusers.pipelines.auto_pipeline import AutoPipelineForText2Image',
            'ImportError: cannot import name X from diffusers.pipelines.foo',
        ].join('\n');
        const onOpen = vi.fn();
        const onReuse = vi.fn();
        render(
            <JobRow
                job={makeJob(longError)}
                statusKind="failed"
                onOpen={onOpen}
                onReuse={onReuse}
                t={noopT}
            />,
        );
        // First line is always visible.
        expect(screen.getByText(/ModuleNotFoundError/i)).toBeTruthy();
        // Disclosure present.
        const disclosure = screen.getByText(/mostrar detalhes/i);
        expect(disclosure).toBeTruthy();
        // Full text not shown yet.
        expect(screen.queryByText(/Traceback/i)).toBeNull();
        // Click the disclosure specifically. ``getByText`` returns
        // the innermost matching element which is the button
        // itself, so fireEvent.click hits our handler.
        fireEvent.click(disclosure);
        // After clicking, the traceback is now rendered.
        expect(screen.getByText(/Traceback/i)).toBeTruthy();
        // And the disclosure text flipped to "Ocultar".
        expect(screen.getByText(/ocultar detalhes/i)).toBeTruthy();
    });

    it('omits the error block entirely when there is no error', () => {
        const onOpen = vi.fn();
        const onReuse = vi.fn();
        const { container } = render(
            <JobRow
                job={makeJob(null)}
                statusKind="done"
                onOpen={onOpen}
                onReuse={onReuse}
                t={noopT}
            />,
        );
        // No error message anywhere.
        expect(container.querySelector('[class*="text-danger"]')).toBeNull();
    });
});