import api from "./client";
import type { ValidateResult, VersionResponse } from "../types";

export async function fetchVersion(): Promise<VersionResponse> {
  const { data } = await api.get<VersionResponse>("/api/version");
  return data;
}

export async function runValidation(): Promise<ValidateResult> {
  const { data } = await api.get<ValidateResult>("/api/validate");
  return data;
}
