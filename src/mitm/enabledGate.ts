import { NextResponse } from "next/server";

/**
 * The MITM subsystem installs a root CA in the system trust store, edits /etc/hosts and runs a
 * TLS-intercepting proxy with sudo. It is off unless the operator opts in with
 * OMNIROUTE_ENABLE_MITM=true (hardened fork). Stop/cleanup (DELETE) stays available so a
 * previously enabled setup can always be undone.
 */
export function isMitmEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  return env.OMNIROUTE_ENABLE_MITM === "true";
}

export function mitmDisabledResponse(): NextResponse | null {
  if (isMitmEnabled()) return null;
  return NextResponse.json(
    {
      error: {
        code: "MITM_DISABLED",
        message:
          "The MITM proxy (system CA install, hosts edits, TLS interception) is disabled. " +
          "Set OMNIROUTE_ENABLE_MITM=true and restart to enable it.",
      },
    },
    { status: 403 }
  );
}
