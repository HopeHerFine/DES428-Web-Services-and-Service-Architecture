export const dynamic = "force-dynamic";

import { Form } from "../../../_ui/client.js";
import { config } from "#lib/config.js";

export default function AdminLoginPage() {
  if (config.externalNotifications) return <div><h1>Admin log in</h1><a className="btn" href="/api/oidc/login?returnTo=/admin/providers">Continue to sign in</a><p className="small muted">Demo admin: admin@edemand.test / eDemand-2026!</p></div>;
  return (
    <div style={{ maxWidth: 420 }}>
      <h1>Admin log in</h1>
      <Form
        endpoint="/api/auth/admin/login"
        redirectTo="/admin/providers"
        submitLabel="Log in"
        fields={[
          { name: "email", label: "Email", type: "email", default: "admin@edemand.test" },
          { name: "password", label: "Password", type: "password" },
        ]}
      />
      <p className="small muted" style={{ marginTop: 12 }}>Seeded: admin@edemand.test / eDemand-2026!</p>
    </div>
  );
}
