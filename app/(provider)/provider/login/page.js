export const dynamic = "force-dynamic";

import { Form } from "../../../_ui/client.js";
import { config } from "#lib/config.js";

export default function ProviderLoginPage() {
  if (config.externalNotifications) return <div><h1>Provider log in</h1><a className="btn" href="/api/oidc/login?returnTo=/provider/dashboard">Continue to sign in</a><p className="small muted">Demo provider: sparkle@example.com / eDemand-2026!</p></div>;
  return (
    <div style={{ maxWidth: 420 }}>
      <h1>Provider log in</h1>
      <Form
        endpoint="/api/auth/provider/login"
        redirectTo="/provider/dashboard"
        submitLabel="Log in"
        fields={[
          { name: "email", label: "Email", type: "email" },
          { name: "password", label: "Password", type: "password" },
        ]}
      />
      <p className="small muted" style={{ marginTop: 12 }}>
        New here? <a href="/provider/register">Register as a provider</a>. Seeded: sparkle@example.com / eDemand-2026!
      </p>
    </div>
  );
}
