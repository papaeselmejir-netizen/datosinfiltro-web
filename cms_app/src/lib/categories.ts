import fs from 'fs';
import path from 'path';

export const CATEGORIES: string[] = JSON.parse(
  fs.readFileSync(path.resolve(process.cwd(), '../categories.json'), 'utf8')
);
