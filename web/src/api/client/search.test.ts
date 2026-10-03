/**
 * Tests for the search request serialiser and `search()` request body.
 *
 * The backend rejects an explicit empty `tag_ids` (spec D11), so the SPA must
 * omit it for an untagged search — without mutating the live UI filter state.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { search, toSearchRequestBody } from './search';
import type { SearchRequest } from '../types';
import { EMPTY_TELEMETRY } from '../types/__fixtures__/searchResponse';

describe('toSearchRequestBody', () => {
  it('drops an empty tag_ids and keeps the other filters', () => {
    const body: SearchRequest = {
      query: 'invoice',
      filters: { tag_ids: [], date_from: '2025-01-01', correspondent_id: 4 },
    };
    expect(JSON.parse(toSearchRequestBody(body))).toEqual({
      query: 'invoice',
      filters: { date_from: '2025-01-01', correspondent_id: 4 },
    });
  });

  it('keeps a non-empty tag_ids', () => {
    const body: SearchRequest = { query: 'invoice', filters: { tag_ids: [7, 9] } };
    expect(JSON.parse(toSearchRequestBody(body))).toEqual(body);
  });

  it('passes null and absent filters through unchanged', () => {
    expect(JSON.parse(toSearchRequestBody({ query: 'q', filters: null }))).toEqual({
      query: 'q',
      filters: null,
    });
    expect(JSON.parse(toSearchRequestBody({ query: 'q' }))).toEqual({ query: 'q' });
  });

  it('does not mutate the request or its filters', () => {
    const filters = { tag_ids: [] as number[], date_to: '2025-12-31' };
    const body: SearchRequest = { query: 'q', filters };
    toSearchRequestBody(body);
    expect(body.filters).toBe(filters);
    expect(filters).toEqual({ tag_ids: [], date_to: '2025-12-31' });
  });
});

describe('search', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends no tag_ids key for an untagged search', async () => {
    const response = JSON.stringify({
      answer: '',
      sources: [],
      plan: { specs: [] },
      stats: { llm_calls: 0, latency_ms: 1, refined: false },
      ...EMPTY_TELEMETRY,
      outcome_kind: 'answered',
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: () => Promise.resolve(response),
    });
    vi.stubGlobal('fetch', fetchMock);

    await search({ query: 'invoice', filters: { tag_ids: [] } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ query: 'invoice', filters: {} });
  });
});
