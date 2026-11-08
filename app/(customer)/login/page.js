export const dynamic = "force-dynamic";

import { Form } from "../../_ui/client.js";
import { config } from "#lib/config.js";

export default function LoginPage() {
  if (config.externalNotifications) return <div><h1>Log in</h1><p>Sign in with your Homeservice account.</p><a className="btn" href="/api/oidc/login?returnTo=/">Continue to sign in</a><p className="small muted">Demo customer: nong@example.com / eDemand-2026!</p></div>;
  return (
    <div style={{ maxWidth: 420 }}>
      <h1>Customer log in</h1>
      <Form
        endpoint="/api/auth/customer/login"
        redirectTo="/"
        submitLabel="Log in"
        fields={[
          { name: "email", label: "Email", type: "email" },
          { name: "password", label: "Password", type: "password" },
        ]}
      />
      <p className="small muted" style={{ marginTop: 12 }}>
        No account? <a href="/register">Sign up</a>. Seeded: nong@example.com / eDemand-2026!
      </p>
    </div>
  );
}
