/**
 * SCVRI Typed API Client
 *
 * Connects Next.js directly to the FastAPI Microservices Gateway (/api/v1/*).
 * Handles:
 *  - Automatic Bearer token authentication
 *  - Correlation ID / Request ID propagation
 *  - Typed responses and error mapping
 */

export interface ApiResponse<T> {
  data: T;
  meta?: {
    page?: number;
    pageSize?: number;
    totalItems?: number;
    totalPages?: number;
  };
}

export interface ApiError {
  type?: string;
  title?: string;
  status: number;
  detail: string;
  instance?: string;
  correlationId?: string;
}

export class ApiClientError extends Error {
  status: number;
  errorDetail: ApiError;

  constructor(status: number, errorDetail: ApiError) {
    super(errorDetail.detail || `API request failed with status ${status}`);
    this.name = "ApiClientError";
    this.status = status;
    this.errorDetail = errorDetail;
  }
}

// Default base URL for client & server components
const getBaseUrl = (): string => {
  if (typeof window !== "undefined") {
    // In browser: use relative path if proxied, or configured public URL
    return process.env.NEXT_PUBLIC_API_URL || "/api/v1";
  }
  // Server-side: use cluster service DNS or local URL
  return process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
};

// Token storage helper
let authToken: string | null = null;

export const setAuthToken = (token: string | null): void => {
  authToken = token;
  if (typeof window !== "undefined") {
    if (token) {
      localStorage.setItem("scvri_access_token", token);
    } else {
      localStorage.removeItem("scvri_access_token");
    }
  }
};

export const getAuthToken = (): string | null => {
  if (authToken) return authToken;
  if (typeof window !== "undefined") {
    return localStorage.getItem("scvri_access_token");
  }
  return null;
};

// Generic fetch wrapper
async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const path = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const url = `${baseUrl}${path}`;

  const token = getAuthToken();
  const correlationId =
    (typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : undefined) ||
    `req-${Date.now()}`;

  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  headers.set("X-Request-ID", correlationId);
  headers.set("X-Correlation-ID", correlationId);

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail: ApiError;
    try {
      errorDetail = await response.json();
    } catch {
      errorDetail = {
        status: response.status,
        detail: response.statusText,
        correlationId,
      };
    }
    throw new ApiClientError(response.status, errorDetail);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

// ── Service Namespaces ────────────────────────────────────────────────────────

export const api = {
  // IAM / Auth
  auth: {
    login: (credentials: { email: string; password: string; mfa_code?: string }) =>
      request<{ access_token: string; refresh_token: string; token_type: string; expires_in: number }>(
        "/auth/token",
        { method: "POST", body: JSON.stringify(credentials) }
      ),
    refreshToken: (refreshToken: string) =>
      request<{ access_token: string; token_type: string; expires_in: number }>(
        "/auth/refresh",
        { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) }
      ),
    getMe: () => request<any>("/users/me"),
  },

  // Supplier Management
  suppliers: {
    list: (params?: { page?: number; limit?: number; search?: string; status?: string }) => {
      const query = new URLSearchParams();
      if (params?.page) query.set("page", String(params.page));
      if (params?.limit) query.set("limit", String(params.limit));
      if (params?.search) query.set("search", params.search);
      if (params?.status) query.set("status", params.status);
      const qs = query.toString();
      return request<any>(`/suppliers${qs ? `?${qs}` : ""}`);
    },
    get: (id: string) => request<any>(`/suppliers/${id}`),
    create: (data: any) =>
      request<any>("/suppliers", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: any) =>
      request<any>(`/suppliers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    getScorecards: (supplierId: string) =>
      request<any>(`/suppliers/${supplierId}/scorecards`),
  },

  // Risk Intelligence
  risk: {
    getSupplierScore: (supplierId: string) =>
      request<any>(`/risk/suppliers/${supplierId}/score`),
    getSummary: () => request<any>("/risk/suppliers/summary"),
    getTrend: (params?: { weeks?: number }) => {
      const qs = params?.weeks ? `?weeks=${params.weeks}` : "";
      return request<any>(`/risk/trend${qs}`);
    },
    getOntimeByWeek: () => request<any>("/risk/ontime-by-week"),
    getByRegion: () => request<any>("/risk/by-region"),
    getShipmentDelays: () => request<any>("/risk/shipment-delays"),
  },

  // Visibility / Shipments / Purchase Orders
  visibility: {
    listPOs: (params?: { supplier_id?: string; status?: string; limit?: number }) => {
      const query = new URLSearchParams();
      if (params?.supplier_id) query.set("supplier_id", params.supplier_id);
      if (params?.status) query.set("status", params.status);
      if (params?.limit) query.set("limit", String(params.limit));
      const qs = query.toString();
      return request<any>(`/purchase-orders${qs ? `?${qs}` : ""}`);
    },
    getPO: (id: string) => request<any>(`/purchase-orders/${id}`),
    listShipments: (params?: { status?: string; carrier?: string; limit?: number }) => {
      const query = new URLSearchParams();
      if (params?.status) query.set("status", params.status);
      if (params?.carrier) query.set("carrier", params.carrier);
      if (params?.limit) query.set("limit", String(params.limit));
      const qs = query.toString();
      return request<any>(`/shipments${qs ? `?${qs}` : ""}`);
    },
    getShipment: (id: string) => request<any>(`/shipments/${id}`),
    getTelemetry: (shipmentId: string) =>
      request<any>(`/telemetry/${shipmentId}`),
  },

  // Alert Engine
  alerts: {
    list: (params?: { status?: string; severity?: string; limit?: number }) => {
      const query = new URLSearchParams();
      if (params?.status) query.set("status", params.status);
      if (params?.severity) query.set("severity", params.severity);
      if (params?.limit) query.set("limit", String(params.limit));
      const qs = query.toString();
      return request<any>(`/alerts${qs ? `?${qs}` : ""}`);
    },
    get: (id: string) => request<any>(`/alerts/${id}`),
    acknowledge: (id: string, notes?: string) =>
      request<any>(`/alerts/${id}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({ notes }),
      }),
    resolve: (id: string, notes?: string) =>
      request<any>(`/alerts/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ notes }),
      }),
  },
};

export default api;
