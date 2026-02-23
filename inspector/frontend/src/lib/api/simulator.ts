import api from "./client";
import type { SimulatorDataResponse } from "../types/simulator";

/**
 * Fetch all rule data needed by the client-side simulator.
 * Returns demographics, ER rules, OLDCARTS/OPD rules, and constants
 * in a single payload.
 */
export async function fetchSimulatorData(): Promise<SimulatorDataResponse> {
  const { data } = await api.get<SimulatorDataResponse>("/api/simulator_data");
  return data;
}
