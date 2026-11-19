/** Public addresses the widget embed snippet uses (nothing secret). */

import { studioEnv } from "@/lib/server/env";

export function GET(): Response {
  const env = studioEnv();
  return Response.json({ gatewayUrl: env.publicGatewayUrl, widgetUrl: `${env.baseUrl}/widget/nexiqon-chat.js` });
}
