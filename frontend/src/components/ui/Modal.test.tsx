import {useState} from 'react';
import {describe, expect, it} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {Modal} from './Modal';

/** Mirrors the page pattern that used to break typing: form state lives in the
 * component that renders <Modal>, and onClose is an inline arrow — so every
 * keystroke re-renders with a fresh onClose identity. */
function ReasonModalHarness() {
    const [open, setOpen] = useState(true);
    const [reason, setReason] = useState('');
    return (
        <Modal open={open} onClose={() => setOpen(false)} title="Reject">
            <textarea
                aria-label="Reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
            />
        </Modal>
    );
}

describe('Modal', () => {
    it('keeps focus in a controlled field across re-renders (typing works)', () => {
        render(<ReasonModalHarness/>);

        const field = screen.getByLabelText('Reason');
        field.focus();
        fireEvent.change(field, {target: {value: 'needs'}});
        fireEvent.change(field, {target: {value: 'needs revision'}});

        expect(field).toHaveValue('needs revision');
        expect(field).toHaveFocus();
    });

    it('still closes on Escape', () => {
        render(<ReasonModalHarness/>);
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        fireEvent.keyDown(document, {key: 'Escape'});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
