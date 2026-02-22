import axios from "axios";

/**
 * Shared axios instance.  In dev mode Next.js rewrites /api/* to
 * localhost:8000, so a relative base URL works everywhere.
 */
const api = axios.create({ baseURL: "/" });

export default api;
