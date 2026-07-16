import {describe, expect, it} from 'vitest';
import {formatCurrency, formatNumber, formatPct, makeUnitFormatter} from './format';

describe('formatCurrency', () => {
    it('abbreviates crores and lakhs the Indian way', () => {
        expect(formatCurrency(35900000)).toBe('₹3.59Cr');
        expect(formatCurrency(139000)).toBe('₹1.39L');
        expect(formatCurrency(2500)).toBe('₹2.5K');
    });

    it('handles decimal strings and invalid input', () => {
        expect(formatCurrency('1875.00')).toBe('₹1.9K');
        expect(formatCurrency('not-a-number')).toBe('₹0');
    });
});

describe('formatPct', () => {
    it('formats with two decimals by default', () => {
        expect(formatPct('93')).toBe('93.00%');
        expect(formatPct(128, 0)).toBe('128%');
    });
});

describe('formatNumber', () => {
    it('groups with the en-IN locale', () => {
        expect(formatNumber(1234567)).toBe('12,34,567');
    });
});

describe('makeUnitFormatter', () => {
    it('prefixes ₹ for currency units (and by default)', () => {
        expect(makeUnitFormatter()('12500')).toBe('₹12,500');
        expect(makeUnitFormatter('INR')('12500')).toBe('₹12,500');
    });

    it('renders plain numbers for non-currency units', () => {
        expect(makeUnitFormatter('outlets')('1200')).toBe('1,200');
        expect(makeUnitFormatter('tonnes', 2)('1234.5')).toBe('1,234.5');
    });

    it('shows a dash for missing values', () => {
        expect(makeUnitFormatter('outlets')(null)).toBe('—');
        expect(makeUnitFormatter()('')).toBe('—');
    });
});
