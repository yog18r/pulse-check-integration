import { describe, expect, it } from 'vitest';
import { breakdown, EMPTY_SUMMARY, headline } from '../../src/core/summarise';

describe('headline and breakdown', () => {
  it('read plainly for none, one and many', () => {
    expect(headline(EMPTY_SUMMARY)).toBe('✅ All devices OK');
    expect(headline({ ...EMPTY_SUMMARY, attention: 1 })).toBe('⚠️ 1 device needs attention');
    expect(headline({ ...EMPTY_SUMMARY, attention: 6 })).toBe('⚠️ 6 devices need attention');
  });

  it('breakdown lists only the kinds of trouble present', () => {
    expect(breakdown(EMPTY_SUMMARY)).toBe('');
    expect(breakdown({ ...EMPTY_SUMMARY, lowBatteries: 1 })).toBe('1 low battery');
    expect(breakdown({ ...EMPTY_SUMMARY, lowBatteries: 4, offline: 1, quiet: 2 })).toBe(
      '4 low batteries · 1 offline · 2 quiet',
    );
  });
});
