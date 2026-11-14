import { createClient } from "../api/gen/client";
import type { _Error as ApiError, Me } from "../api/gen/types.gen";
import { AppError } from "./errors";
import type { Session } from "./models";

export function contractError(message: string): AppError {
  return new AppError(0, {
    code: "CONTRACT_MISMATCH",
    message,
    requestId: "unavailable",
  });
}
export function requireValue<T>(value: T | null | undefined, field: string): T {
  if (value === undefined || value === null)
    throw contractError(`API response is missing ${field}.`);
  return value;
}
export interface ApiResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}
export class ApiConnection {
  readonly client;
  private csrfToken = "";
  constructor(baseUrl = "/api/v1") {
    // The generated fetch runtime constructs Request objects, which need an absolute URL.
    const origin = globalThis.location?.origin ?? "http://127.0.0.1";
    this.client = createClient({
      baseUrl: new URL(baseUrl.replace(/\/$/, "") + "/", origin).href.replace(
        /\/$/,
        "",
      ),
      credentials: "include",
    });
  }
  async read<T>(result: Promise<ApiResult<T>>): Promise<T> {
    const { data, error, response } = await result;
    if (!response.ok) {
      const body = (
        typeof error === "object" && error !== null ? error : {}
      ) as Partial<ApiError>;
      const fieldErrors: Record<string, string> = {};
      const uiField: Record<string, string> = {
        username: "name",
        videoInspectionId: "videoId",
        videoOffsetSeconds: "offsetSeconds",
      };
      for (const item of body.fieldErrors ?? [])
        if (item.field && item.message)
          fieldErrors[uiField[item.field] ?? item.field] = item.message;
      throw new AppError(
        response.status,
        {
          code: body.code ?? `HTTP_${response.status}`,
          message: body.message ?? `API request failed (${response.status}).`,
          fieldErrors,
          requestId:
            body.requestId ??
            response.headers.get("X-Request-ID") ??
            "unavailable",
        },
        response.headers.get("Retry-After") ?? undefined,
      );
    }
    return data as T; // Generated return type includes undefined for the error branch, handled above.
  }
  async identity(result: Promise<ApiResult<Me>>): Promise<Session> {
    const response = await result;
    const me = await this.read(Promise.resolve(response));
    this.csrfToken =
      this.cookieToken() ?? response.response.headers.get("X-CSRF-Token") ?? "";
    const role = requireValue(me.role, "Me.role");
    if (role !== "OPERATOR" && role !== "MANAGER")
      throw contractError("API returned an unknown role.");
    return {
      user: { name: requireValue(me.username, "Me.username"), role },
      csrfToken: this.csrfToken,
    };
  }
  mutationHeaders() {
    const token = this.cookieToken() ?? this.csrfToken;
    if (!token)
      throw contractError(
        "The CSRF cookie is missing. Sign in again before making changes.",
      );
    return { "X-CSRF-Token": token };
  }
  private cookieToken() {
    if (typeof document === "undefined") return undefined;
    return document.cookie
      .split("; ")
      .find((cookie) => cookie.startsWith("filegrid_csrf="))
      ?.slice("filegrid_csrf=".length);
  }
  clearSession() {
    this.csrfToken = "";
  }
}
