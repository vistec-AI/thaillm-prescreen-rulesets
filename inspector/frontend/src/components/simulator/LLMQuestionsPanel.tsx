"use client";

import { useState } from "react";

/** A single LLM Q&A pair passed back when the user proceeds to results */
export interface LLMAnswerPair {
  question: string;
  answer: string;
}

interface LLMQuestionsPanelProps {
  questions: string[];
  loading: boolean;
  error: string | null;
  /** Called with the LLM answers when the user proceeds to results */
  onContinue: (llmAnswers: LLMAnswerPair[]) => void;
  predictionLoading?: boolean;
}

/**
 * Display component for LLM-generated follow-up questions (phase 6).
 * Each question is rendered as a free text input that must be filled
 * before the user can proceed to results.
 */
export default function LLMQuestionsPanel({
  questions,
  loading,
  error,
  onContinue,
  predictionLoading = false,
}: LLMQuestionsPanelProps) {
  // Track free text answers for each LLM-generated question
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const allFilled =
    questions.length > 0 &&
    questions.every((_, i) => (answers[i] ?? "").trim().length > 0);

  const updateAnswer = (index: number, value: string) => {
    setAnswers((prev) => ({ ...prev, [index]: value }));
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">
          LLM Follow-up Questions
        </h3>
        <div className="border border-gray-200 rounded-lg p-6 bg-white flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-gray-500">
            Generating follow-up questions...
          </p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">
          LLM Follow-up Questions
        </h3>
        <div className="border border-red-200 rounded-lg p-4 bg-red-50">
          <p className="text-sm text-red-600">{error}</p>
        </div>
        <button
          onClick={() => onContinue([])}
          className="bg-gray-600 text-white px-4 py-2 rounded hover:bg-gray-700 transition-colors text-sm font-medium"
        >
          Skip to Results
        </button>
      </div>
    );
  }

  if (questions.length === 0) {
    return (
      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">
          LLM Follow-up Questions
        </h3>
        <div className="border border-gray-200 rounded-lg p-4 bg-white">
          <p className="text-sm text-gray-500">
            No additional questions generated.
          </p>
        </div>
        <button
          onClick={() => onContinue([])}
          className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors text-sm font-medium"
        >
          Continue to Results
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h3 className="text-lg font-semibold text-gray-800">
        LLM Follow-up Questions
      </h3>
      <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-4">
        <p className="text-xs text-gray-500">
          Please answer the following follow-up questions:
        </p>
        {questions.map((q, i) => (
          <div key={i} className="space-y-1">
            <label className="block text-sm font-medium text-gray-700">
              {i + 1}. {q}
            </label>
            <textarea
              value={answers[i] ?? ""}
              onChange={(e) => updateAnswer(i, e.target.value)}
              placeholder="กรุณาตอบคำถาม..."
              rows={2}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent resize-y"
            />
          </div>
        ))}
      </div>
      <button
        onClick={() => {
          const pairs: LLMAnswerPair[] = questions.map((q, i) => ({
            question: q,
            answer: (answers[i] ?? "").trim(),
          }));
          onContinue(pairs);
        }}
        disabled={!allFilled || predictionLoading}
        className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
          allFilled && !predictionLoading
            ? "bg-blue-500 text-white hover:bg-blue-600"
            : "bg-gray-300 text-gray-500 cursor-not-allowed"
        }`}
      >
        {predictionLoading ? (
          <span className="flex items-center gap-2">
            <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            Running prediction...
          </span>
        ) : (
          "Continue to Results"
        )}
      </button>
    </div>
  );
}
