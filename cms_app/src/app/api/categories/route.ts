import { NextResponse } from 'next/server';
import { requireAdmin } from '@/lib/admin';
import { CATEGORIES } from '@/lib/categories';

export async function GET(request: Request) {
  const denied = requireAdmin(request);
  if (denied) return denied;
  return NextResponse.json({ success: true, categories: CATEGORIES });
}
