import api from "./client";
import type { DemographicResponse, MutationResult } from "../types";

export async function fetchPastHistory(): Promise<DemographicResponse> {
  const { data } = await api.get<DemographicResponse>("/api/past_history");
  return data;
}

export async function updatePastHistory(
  qid: string,
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/update_past_history", {
    qid,
    data: payload,
  });
  return data;
}

export async function addPastHistory(
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/add_past_history", {
    data: payload,
  });
  return data;
}

export async function deletePastHistory(
  qid: string,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/delete_past_history", {
    qid,
  });
  return data;
}
