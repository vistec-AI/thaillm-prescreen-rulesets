import api from "./client";
import type { GraphResponse, SymptomsResponse, MutationResult } from "../types";

export async function fetchSymptoms(): Promise<SymptomsResponse> {
  const { data } = await api.get<SymptomsResponse>("/api/symptoms");
  return data;
}

export async function fetchGraph(
  symptom: string,
  mode: string,
): Promise<GraphResponse> {
  const { data } = await api.get<GraphResponse>("/api/graph", {
    params: { symptom, mode },
  });
  return data;
}

export async function updateQuestion(payload: {
  source: string | null;
  symptom: string;
  qid: string;
  data: Record<string, unknown>;
}): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/update_question", payload);
  return data;
}
