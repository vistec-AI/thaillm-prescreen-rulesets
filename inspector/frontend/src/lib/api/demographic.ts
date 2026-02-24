import api from "./client";
import type { DemographicResponse, MutationResult } from "../types";

export async function fetchDemographic(): Promise<DemographicResponse> {
  const { data } = await api.get<DemographicResponse>("/api/demographic");
  return data;
}

export async function updateDemographic(
  qid: string,
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/update_demographic", {
    qid,
    data: payload,
  });
  return data;
}

export async function addDemographic(
  payload: Record<string, unknown>,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/add_demographic", {
    data: payload,
  });
  return data;
}

export async function deleteDemographic(
  qid: string,
): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/delete_demographic", {
    qid,
  });
  return data;
}
