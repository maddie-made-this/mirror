import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

/**
 * Refreshes the Supabase auth session on every request and propagates any
 * rotated token cookies onto the response.
 *
 * The previous version called getUser() on a throwaway client whose `setAll`
 * was a no-op — so when Supabase rotated the refresh token (which it does right
 * after login), the new cookies were silently dropped. The browser kept the old,
 * now-invalidated refresh token and every subsequent getSession() returned null.
 */
export async function updateSession(request: NextRequest) {
  // Start with a passthrough response; setAll rebuilds it with fresh cookies.
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(supabaseUrl!, supabaseKey!, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        // Write rotated cookies to the request (for any downstream handler)
        // and to the response (so the browser actually receives them).
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value)
        );
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options)
        );
      },
    },
  });

  // getUser() validates the session and rotates a near-expiry token — the
  // rotated cookies flow through setAll above onto supabaseResponse.
  await supabase.auth.getUser();

  return supabaseResponse;
}
