import fs from 'fs';
import path from 'path';

export const BASE_DIR = path.resolve(process.cwd(), '..');
export const DRAFTS_DIR = path.join(BASE_DIR, 'drafts');
export const OUTPUT_DIR = path.join(BASE_DIR, 'published');

export function resolveDraft(id: unknown): string | null {
  if (typeof id !== 'string' || !/^\d{4}-\d{2}-\d{2}\/[\p{L}\p{N}_,.-]+\/[\p{L}\p{N}_.-]+\.json$/u.test(id)) {
    return null;
  }
  const resolved = path.resolve(DRAFTS_DIR, ...id.split('/'));
  return resolved.startsWith(DRAFTS_DIR + path.sep) ? resolved : null;
}

export function listDraftFiles(dir = DRAFTS_DIR): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? listDraftFiles(file) : entry.name.endsWith('.json') ? [file] : [];
  });
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Error inesperado';
}
