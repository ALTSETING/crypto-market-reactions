export type ApiV1ErrorCode =
  | "INVALID_PARAMETER"
  | "INVALID_CURSOR"
  | "UNAUTHORIZED"
  | "RATE_LIMITED"
  | "EVENT_NOT_FOUND"
  | "SERVICE_UNAVAILABLE";

export class ApiV1Error extends Error {
  constructor(
    readonly status: 400 | 401 | 404 | 429 | 500 | 503,
    readonly code: ApiV1ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "ApiV1Error";
  }
}

