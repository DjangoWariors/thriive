import {describe, expect, it} from 'vitest';
import {render, screen} from '@testing-library/react';
import {StatusBadge} from './StatusBadge';

describe('StatusBadge', () => {
    it('maps known statuses to friendly labels', () => {
        render(<StatusBadge status="completed"/>);
        expect(screen.getByText('Completed')).toBeInTheDocument();
    });

    it('maps report execution statuses used by the reports page', () => {
        render(<StatusBadge status="queued"/>);
        expect(screen.getByText('Queued')).toBeInTheDocument();
    });

    it('falls back to the raw status when unmapped', () => {
        render(<StatusBadge status="some_custom_state"/>);
        expect(screen.getByText('some_custom_state')).toBeInTheDocument();
    });
});
