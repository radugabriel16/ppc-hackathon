export interface ErrorBody {
  code: string;
  message: string;
  fieldErrors?: Record<string, string>;
  requestId: string;
}
export class AppError extends Error {
  constructor(
    public status: number,
    public body: ErrorBody,
    public retryAfter?: string,
  ) {
    super(body.message);
    this.name = "AppError";
  }
}
export function errorText(error: unknown): string {
  if (error instanceof AppError)
    return `${error.body.message} · Request ID: ${error.body.requestId}`;
  return error instanceof Error
    ? error.message
    : "An unexpected error occurred.";
}
