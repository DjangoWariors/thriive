import {describe, expect, it} from 'vitest';
import {activeNetworkTab} from './index';

describe('activeNetworkTab', () => {
    it('maps each tab path and its children to the right tab', () => {
        expect(activeNetworkTab('/network/people')).toBe('/network/people');
        expect(activeNetworkTab('/network/people/42')).toBe('/network/people');
        expect(activeNetworkTab('/network/territories')).toBe('/network/territories');
        expect(activeNetworkTab('/network/owners')).toBe('/network/owners');
        expect(activeNetworkTab('/network/setup')).toBe('/network/setup');
        expect(activeNetworkTab('/network/setup/role-types')).toBe('/network/setup');
        expect(activeNetworkTab('/network/setup/channels')).toBe('/network/setup');
    });

    it('defaults to People for the bare workspace path', () => {
        expect(activeNetworkTab('/network')).toBe('/network/people');
    });

    it('never confuses a prefix with a tab (no /network/peoples surprises)', () => {
        expect(activeNetworkTab('/network/ownership-report')).toBe('/network/people');
    });
});
