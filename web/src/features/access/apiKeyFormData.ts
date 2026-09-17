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
    // Deliberately scoped wording: a key never exceeds its owner's role, so
    // for a Member this grants key management over their OWN keys and nothing
    // more — user administration additionally needs an admin account. The
    // panels became reachable by Members when /settings/keys stopped being
    // admin-only, and the previous copy ("Manage users and other keys") was
    // untrue for every Member who can now read it.
    description: 'Manage keys you own. User administration additionally requires an admin account.',
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
