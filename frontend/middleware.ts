import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Auth is not yet implemented — all routes are open
export function middleware(_request: NextRequest) {
  return NextResponse.next();
}
