import api from "./client";
import type { ConstantsResponse } from "../types";

export async function fetchConstants(): Promise<ConstantsResponse> {
  const { data } = await api.get<ConstantsResponse>("/api/constants");
  return data;
}
