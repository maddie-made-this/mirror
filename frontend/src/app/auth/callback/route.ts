import { NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'

export async function GET(request: Request) {
  const url = new URL(request.url)
  const { searchParams } = url
  const code = searchParams.get('code')

  const rawNext = searchParams.get('next') ?? '/'
  // Only allow relative paths to prevent open-redirect attacks
  const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/'

  // Behind the Cloudflare tunnel the Next.js server sees the request as
  // arriving at localhost — new URL(request.url).origin is the *internal*
  // address, not the public hostname. Redirecting to it sends the browser to
  // https://localhost (no TLS → ERR_SSL_PROTOCOL_ERROR). Trust the forwarded
  // Host header (cloudflared preserves it as mirror.dev) instead.
  const forwardedHost =
    request.headers.get('x-forwarded-host') ?? request.headers.get('host')
  const isLocalHost =
    !forwardedHost ||
    forwardedHost.startsWith('localhost') ||
    forwardedHost.startsWith('127.0.0.1')
  const proto = isLocalHost
    ? 'http'
    : request.headers.get('x-forwarded-proto') ?? 'https'
  const origin = forwardedHost ? `${proto}://${forwardedHost}` : url.origin

  if (code) {
    // Await the creation of the client because cookies() is async
    const supabase = await createClient()
    const { error } = await supabase.auth.exchangeCodeForSession(code)

    if (!error) {
      return NextResponse.redirect(`${origin}${next}`)
    }
  }

  // Return the user to an error page if the code exchange fails
  return NextResponse.redirect(`${origin}/auth/auth-error`)
}
