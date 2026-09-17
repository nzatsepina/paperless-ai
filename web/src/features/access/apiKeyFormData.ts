/**
 * Shared form data for API key create and edit panels.
 *
 * Extracted here to avoid duplication between `APIKeyCreatePanel` and
 * `APIKeyEditPanel`, which previously each defined byte-identical copies
 * (CODE_GUIDELINES §1.3 — every line is a liability).
 *
 * Allowed deps: api/types (leaf; no React, no hooks, no components).
 */
import type { ApiScope } from '../../api/types';

/** The selectable scopes, with their human descriptions. */
export const SCOPES: { id: ApiScope; description: string }[] = [
  {
    id: 'api',
    description: 'REST endpoints under /api/* — search, facets, stats, reconcile.',
  },
  {
    id: 'mcp',
    description:
      'The MCP server at /mcp — semantic_search, keyword_search, fetch_documents, list_filters, deep_search.',
  },
  {
    id: 'admin',
    // Avoid the literal "API" in this description: APIKeyCreatePanel and
    // APIKeyEditPanel select scope checkboxes by accessible name (/api/i), the
    // label wraps the input so the row's whole text forms that name, and
    // reusing the word makes the admin row collide with the api row.
    //
    // ScopeChecklist renders this string with no role branching, so it is read
    // by admins and members alike and must be true for both: an admin's key
    // lists and revokes every user's (key_store.list_all in _list_api_keys,
    // the role check in _delete_api_key), a member's only their own.
    description:
      "Manage keys \u2014 your own, or every user's if you are an admin. User administration additionally requires an admin account. Grant sparingly.",
  },
];

/** Expiry quick-pick options, in days. `null` means "never expires". */
export const EXPIRY_CHOICES: { label: string; days: number | null }[] = [
  { label: 'Never', days: null },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '365 days', days: 365 },
];

/** Convert a day-count to an ISO expiry timestamp, or null for "never". */
export function expiryIso(days: number | null): string | null {
  if (days === null) return null;
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}
