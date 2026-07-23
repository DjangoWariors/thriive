import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { EMPTY_MEASURE, MeasurementBuilder } from './MeasurementBuilder';
import type { MeasureConfig } from '../../types/kpi';

// Mirrors AMOUNT_FIELDS / DIMENSION_FIELDS in the backend calculator. The two halves are not
// interchangeable: an amount column can't be counted distinct, and the backend rejects the mix.
const AMOUNT_FIELDS = ['net_amount', 'gross_amount', 'quantity', 'base_quantity'];
const DIMENSION_FIELDS = ['outlet_code', 'bill_ref', 'sku_code'];

// The builder is controlled, so a harness owns the config and transitions compose the way they do
// in the wizard. `latest` is what the wizard would submit at any point.
let latest: MeasureConfig;

function Harness() {
  const [config, setConfig] = useState<MeasureConfig>({ ...EMPTY_MEASURE });
  latest = config;
  return <MeasurementBuilder value={config} onChange={setConfig} />;
}

const setAggregation = (value: string) =>
  fireEvent.change(screen.getByLabelText('Aggregation'), { target: { value } });

/**
 * The check that generalises past any single field pairing: the dropdown must be showing what the
 * config holds. React selects the first option when the value matches none, so a desync is
 * invisible on screen — the user reads a field the config doesn't have. Only this assertion sees it.
 */
function expectFieldInSync(label: 'Field' | 'Distinct field') {
  const select = screen.getByLabelText(label) as HTMLSelectElement;
  expect(select.value).toBe(latest.measure_field);
}

describe('MeasurementBuilder aggregation switching', () => {
  it('starts on a summed amount', () => {
    render(<Harness />);
    expect(latest.aggregation).toBe('sum');
    expect(AMOUNT_FIELDS).toContain(latest.measure_field);
    expectFieldInSync('Field');
  });

  it('moves the field into the distinct family when switching to a distinct count', () => {
    // The regression: the field used to survive the switch, so a preview asked the backend to
    // count distinct values of net_amount — a decimal column — and got a 500.
    render(<Harness />);
    setAggregation('count_distinct');

    expect(latest.aggregation).toBe('count_distinct');
    expect(DIMENSION_FIELDS).toContain(latest.measure_field);
    expectFieldInSync('Distinct field');
  });

  it('moves the field back to an amount when leaving a distinct count', () => {
    render(<Harness />);
    setAggregation('count_distinct');
    setAggregation('sum');

    expect(AMOUNT_FIELDS).toContain(latest.measure_field);
    expectFieldInSync('Field');
  });

  it('drops the qualifying threshold when the aggregation is no longer a distinct count', () => {
    // `having` is only meaningful under count_distinct; the backend rejects it anywhere else.
    render(<Harness />);
    setAggregation('count_distinct');
    fireEvent.click(screen.getByLabelText(/Effective Coverage/));
    expect(latest.having).toBeTruthy();

    setAggregation('sum');
    expect(latest.having).toBeUndefined();
  });

  it('clears the weighted-distribution fields when leaving a distinct count', () => {
    render(<Harness />);
    setAggregation('count_distinct');
    fireEvent.click(screen.getByLabelText(/Weight by sales/));
    expect(latest.aggregation).toBe('weighted_distinct');
    expect(DIMENSION_FIELDS).toContain(latest.group_field);
    expect(AMOUNT_FIELDS).toContain(latest.weight_field);

    setAggregation('sum');
    expect(latest.group_field).toBeUndefined();
    expect(latest.weight_field).toBeUndefined();
    expect(latest.weight_scope).toBeUndefined();
  });

  it('keeps the field in sync through any order of switches', () => {
    render(<Harness />);
    for (const agg of ['count_distinct', 'count', 'sum', 'count_distinct', 'sum', 'count', 'count_distinct']) {
      setAggregation(agg);
      if (agg === 'count') continue; // a plain row count has no field to pick
      expectFieldInSync(agg === 'count_distinct' ? 'Distinct field' : 'Field');
    }
  });
});
