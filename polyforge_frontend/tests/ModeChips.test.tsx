import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { ModeChips } from '../src/components/jobs/ModeChips';

describe('ModeChips', () => {
    it('renders all four modes', () => {
        const onChange = vi.fn();
        const { getAllByRole } = render(
            <ModeChips value="text" onChange={onChange} />,
        );
        const tabs = getAllByRole('tab');
        expect(tabs.length).toBe(4);
        expect(tabs[0].id).toBe('mode-tab-text');
        expect(tabs[1].id).toBe('mode-tab-image');
        expect(tabs[2].id).toBe('mode-tab-multiview');
        expect(tabs[3].id).toBe('mode-tab-texture');
    });

    it('marks the active tab via aria-selected', () => {
        const onChange = vi.fn();
        const { getByRole } = render(
            <ModeChips value="image" onChange={onChange} />,
        );
        expect(getByRole('tab', { selected: true }).id).toBe('mode-tab-image');
    });

    it('does NOT disable modes that the backend marks unavailable', () => {
        // The UX change: previously the chip was a true ``<button disabled>``
        // when the model wasn't loaded, which made the form feel broken.
        // Now every chip is clickable; the unavailable state is purely
        // visual (amber dot + tooltip with the reason).
        const onChange = vi.fn();
        const availability = {
            text: { available: false, reason: 'no model' },
            image: { available: true, reason: null },
            multiview: { available: false, reason: 'no model' },
            texture: { available: false, reason: 'no model' },
        };
        const { getByRole, queryAllByTestId } = render(
            <ModeChips
                value="text"
                onChange={onChange}
                availability={availability}
            />,
        );
        // Use the stable id to disambiguate when the accessible name
        // contains the word "text" both as a label and as a status.
        const textTab = getByRole('tab', { selected: true });
        const imageTab = document.querySelector<HTMLElement>('#mode-tab-image')!;
        expect(textTab).not.toBeNull();
        expect(imageTab).not.toBeNull();
        // No chip should have the native ``disabled`` attribute.
        expect(textTab!.hasAttribute('disabled')).toBe(false);
        expect(imageTab!.hasAttribute('disabled')).toBe(false);
        // The unavailable indicator dot is present on the three that
        // the backend flagged.
        const indicators = queryAllByTestId('mode-unavailable-indicator');
        expect(indicators.length).toBe(3);
    });

    it('fires onChange when an unavailable chip is clicked', () => {
        const onChange = vi.fn();
        const availability = {
            text: { available: false, reason: 'no model' },
            image: { available: false, reason: 'no model' },
            multiview: { available: false, reason: 'no model' },
            texture: { available: false, reason: 'no model' },
        };
        const { container } = render(
            <ModeChips
                value="text"
                onChange={onChange}
                availability={availability}
            />,
        );
        // Pick by stable id to dodge the long accessible name.
        const imageTab = container.querySelector<HTMLButtonElement>('#mode-tab-image');
        expect(imageTab).not.toBeNull();
        fireEvent.click(imageTab!);
        expect(onChange).toHaveBeenCalledWith('image');
    });

    it('navigates between chips with arrow keys', () => {
        const onChange = vi.fn();
        const { getByRole } = render(
            <ModeChips value="text" onChange={onChange} />,
        );
        const textTab = getByRole('tab', { name: 'Text', selected: true });
        textTab.focus();
        fireEvent.keyDown(textTab, { key: 'ArrowRight' });
        expect(onChange).toHaveBeenCalledWith('image');
    });
});