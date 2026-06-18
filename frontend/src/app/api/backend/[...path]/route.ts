import { NextRequest } from "next/server";

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export async function GET(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxyBackendRequest(request, context);
}

async function proxyBackendRequest(request: NextRequest, context: RouteContext): Promise<Response> {
  const backendUrl = backendBaseUrl();
  if (!backendUrl) {
    return Response.json({ error: "CLI_AGENT_BACKEND_URL is not configured" }, { status: 500 });
  }

  const { path } = await context.params;
  const targetPath = path.map((part) => encodeURIComponent(part)).join("/");
  const target = new URL(targetPath, `${backendUrl}/`);
  target.search = request.nextUrl.search;
  const body = request.method === "GET" ? undefined : await request.arrayBuffer();

  let response: Response;
  try {
    response = await fetch(target, {
      method: request.method,
      headers: backendRequestHeaders(request),
      body,
      redirect: "manual",
    });
  } catch (error) {
    console.error("Backend proxy request failed", { target: target.toString(), error });
    return Response.json(
      {
        error: "Backend request failed",
        details: errorMessage(error),
      },
      { status: 502 },
    );
  }

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: responseHeaders(response),
  });
}

function backendBaseUrl(): string | null {
  const rawUrl = process.env.CLI_AGENT_BACKEND_URL?.trim();
  if (!rawUrl) {
    return null;
  }
  return rawUrl.replace(/\/$/, "");
}

function backendRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  const token = process.env.CLI_AGENT_BACKEND_BEARER_TOKEN;

  if (contentType) {
    headers.set("content-type", contentType);
  }
  if (accept) {
    headers.set("accept", accept);
  }
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }
  headers.set("ngrok-skip-browser-warning", "true");

  return headers;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "Unknown backend connection error";
}

function responseHeaders(response: Response): Headers {
  const headers = new Headers();
  for (const [name, value] of response.headers) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      headers.set(name, value);
    }
  }
  return headers;
}
