import api from "./client";
import type { DemographicResponse, MutationResult } from "../types";

export async function fetchPersonalHistory(): Promise<DemographicResponse> {
  const { data } = await api.get<DemographicResponse>("/api/personal_history");
  return data;
}

export async function updatePersonalHistory(
  qid: string,
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/update_personal_history", {
    qid,
    data: payload,
  });
  return data;
}

export async function addPersonalHistory(
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/add_personal_history", {
    data: payload,
  });
  return data;
}

export async function deletePersonalHistory(
  qid: string,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/delete_personal_history", {
    qid,
  });
  return data;
}
