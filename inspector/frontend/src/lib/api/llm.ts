import api from "./client";

export interface QAPairPayload {
  question: string;
  answer: unknown;
  source: "rule_based" | "llm_generated";
  qid: string | null;
  question_type: string | null;
  phase: number | null;
}

export interface GenerateQuestionsResponse {
  questions: string[];
  available: boolean;
  error?: string;
}

/**
 * Call the backend to generate LLM follow-up questions from rule-based QA history.
 */
export async function generateQuestions(
  qaPairs: QAPairPayload[]
): Promise<GenerateQuestionsResponse> {
  const { data } = await api.post<GenerateQuestionsResponse>(
    "/api/simulator/generate_questions",
    { qa_pairs: qaPairs }
  );
  return data;
}

export interface PredictionDiagnosis {
  disease_id: string;
}

export interface PredictResponse {
  available: boolean;
  prediction: {
    diagnoses: PredictionDiagnosis[];
    departments: string[];
    severity: string;
  } | null;
  /** Error message when prediction was attempted but failed */
  error?: string;
}

/**
 * Call the backend to run DDx prediction from Q&A history.
 */
export async function predict(
  qaPairs: QAPairPayload[],
  minSeverity: string | null,
  erOverride: boolean
): Promise<PredictResponse> {
  const { data } = await api.post<PredictResponse>(
    "/api/simulator/predict",
    {
      qa_pairs: qaPairs,
      min_severity: minSeverity,
      er_override: erOverride,
    }
  );
  return data;
}
