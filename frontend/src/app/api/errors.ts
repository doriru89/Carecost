/** The mock has no fixture for this request. Shown as such; never filled with made-up numbers. */
export class NoMockData extends Error {
  constructor(what: string) {
    super(what);
    this.name = "NoMockData";
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

