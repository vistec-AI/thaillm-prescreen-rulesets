import api from "./client";
import type { ErChecklistResponse, ErSymptomsResponse, MutationResult } from "../types";

export async function fetchErSymptoms(): Promise<ErSymptomsResponse> {
  const { data } = await api.get<ErSymptomsResponse>("/api/er_symptoms");
  return data;
}

export async function fetchErChecklist(
  mode: string,
  symptom?: string,
): Promise<ErChecklistResponse> {
  const params: Record<string, string> = { mode };
  if (symptom) params.symptom = symptom;
  const { data } = await api.get<ErChecklistResponse>("/api/er_checklist", { params });
  return data;
}

export async function updateErQuestion(payload: {
  mode: string;
  symptom: string | null;
  qid: string;
  data: Record<string, unknown>;
}): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/update_er_question", payload);
  return data;
}

export async function addErQuestion(payload: {
  mode: string;
  symptom: string | null;
  data: Record<string, unknown>;
}): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/add_er_question", payload);
  return data;
}

export async function deleteErQuestion(payload: {
  mode: string;
  symptom: string | null;
  qid: string;
}): Promise<MutationResult> {
  const { data } = await api.post<MutationResult>("/api/delete_er_question", payload);
  return data;
}
