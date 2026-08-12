import {
  LoginCredentials,
  LoginResponse,
  User,
  TenantRegistration,
  TenantRegistrationResponse,
  SlugCheckResponse,
  Tenant,
  TenantStats,
  PaginatedResponse,
  DashboardMetrics,
  Department,
  AppSettings,
  ShiftStatusType,
  UserPreferences,
  OrgLevel,
  OrgLevelItem,
  OrgTreeResponse,
  OrgNodeDetail,
  OrgNodeMembersResponse,
  ApprovalChainResponse,
  LeaveTypeConfig,
  LeavePolicy,
  LeavePolicyEntitlement,
  LeaveBalance,
  LeaveApplication,
  LeaveApproverAssignment,
  ApprovalChainPreviewItem,
  TeamStats,
  OvertimeCategory,
  EmployeeTypeConfig,
  ScheduleFormatConfig,
  SalaryGrade,
  EmployeeSalaryAssignment,
  DeductionType,
  PayrollPeriod,
  PayrollItem,
  PayrollSummary,
  MyPermissionsResponse,
  PermissionMatrixResponse,
  RolePermissionEntry,
  AttendanceRecord,
  OvertimeLog,
  TardinessRecord,
  PolicyRule,
  PolicySimulateResult,
  DataSource,
  DataExportConfig,
  PreviewResponse,
  CustomColumn,
  FilterCondition,
  ScheduledExport,
  ScheduleChangeRequest,
  ScheduleSnapshot,
  OvertimeTrendsResponse,
  OvertimePaidUnpaidResponse,
  LeaveTrendsResponse,
  AttendanceSummaryResponse,
  AnalyticsOverviewResponse,
  PayoutSchedule,
  PayoutScheduleInput,
  CompensationItem,
  CompensationItemInput,
  CurrentSalaryRow,
  RaiseResultRow,
  MyPayslipSummary,
  MyPayslipDetail,
  SnapshotPreview,
  SnapshotApplyResult,
  ScheduleLintViolation,
  SalaryEnrollmentRow,
  SalaryRequestRow,
  MySalaryStatus,
  SalaryRequestByToken,
  NotificationList,
} from '@/types';

const CSRF_COOKIE = 'csrf_token';
const CSRF_HEADER = 'X-CSRF-Token';
const REQUEST_TIMEOUT_MS = 30_000;
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

// Endpoints where a 401 means "bad credentials", not "expired session" — a token
// refresh + retry would be pointless (or loop), so they opt out of the auto-retry.
// NOTE: `/auth/me`, `/auth/logout` etc. are intentionally NOT here — they must be
// able to refresh-and-retry so a hard reload recovers on the first load.
const NO_REFRESH_RETRY_PATHS = [
  '/api/v1/auth/login',
  '/api/v1/auth/2fa/verify',
  '/api/v1/auth/refresh',
];

/** A single scheduling conflict returned by the shift endpoints (HTTP 409 for
 * a single shift, or in `skipped_conflicts` for a bulk create). */
export interface ScheduleConflict {
  employee_id: number;
  date: string;
  type: string;
  forceable: boolean;
  message: string;
}

export interface ShiftBulkCreateResult {
  created: unknown[];
  skipped_conflicts: ScheduleConflict[];
}

/** Error thrown for any non-2xx response. Preserves the HTTP status and the
 * parsed `detail` payload so callers can react to structured errors (e.g. the
 * 409 schedule-conflict body) instead of only seeing a flattened message. */
export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Type guard: a 409 schedule-conflict error with a `conflicts` list. */
export function isScheduleConflictError(
  err: unknown,
): err is ApiError & { detail: { message: string; conflicts: ScheduleConflict[] } } {
  return (
    err instanceof ApiError &&
    err.status === 409 &&
    typeof err.detail === 'object' &&
    err.detail !== null &&
    Array.isArray((err.detail as { conflicts?: unknown }).conflicts)
  );
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

class ApiClient {
  private baseUrl: string;
  /** De-duplicates concurrent refreshes so a burst of 401s triggers one call. */
  private refreshPromise: Promise<boolean> | null = null;
  /** Invoked when the session is unrecoverable, so the app can redirect. */
  private onSessionExpired: (() => void) | null = null;

  constructor() {
    this.baseUrl = process.env.NEXT_PUBLIC_API_URL ?? '';
  }

  setSessionExpiredHandler(handler: (() => void) | null) {
    this.onSessionExpired = handler;
  }

  private getHeaders(method: string): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Auth travels in httpOnly cookies that JS cannot read. The only thing we
    // attach here is the CSRF token, echoed back from a readable cookie to
    // prove the request originated from our own page rather than a third party.
    if (UNSAFE_METHODS.has(method)) {
      const csrf = readCookie(CSRF_COOKIE);
      if (csrf) {
        headers[CSRF_HEADER] = csrf;
      }
    }

    return headers;
  }

  private async handleResponse(response: Response) {
    if (!response.ok) {
      let rawDetail: unknown = 'An error occurred';
      try {
        const data = await response.json();
        rawDetail = data.detail ?? data;
      } catch {
        rawDetail = response.statusText;
      }
      // Build a human-readable message but keep the structured detail so
      // callers can inspect richer error bodies (e.g. 409 schedule conflicts).
      let message: string;
      if (typeof rawDetail === 'string') {
        message = rawDetail;
      } else if (
        rawDetail && typeof rawDetail === 'object' &&
        typeof (rawDetail as { message?: unknown }).message === 'string'
      ) {
        message = (rawDetail as { message: string }).message;
      } else {
        message = JSON.stringify(rawDetail);
      }
      throw new ApiError(message, response.status, rawDetail);
    }
    if (response.status === 204) {
      return null;
    }
    return response.json();
  }

  private async refreshToken(): Promise<boolean> {
    if (typeof window === 'undefined') return false;

    if (!this.refreshPromise) {
      this.refreshPromise = (async () => {
        try {
          // The refresh token is an httpOnly cookie; nothing to send in a body.
          const response = await fetch(`${this.baseUrl}/api/v1/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: this.getHeaders('POST'),
          });
          return response.ok;
        } catch {
          return false;
        } finally {
          this.refreshPromise = null;
        }
      })();
    }

    return this.refreshPromise;
  }

  private async request(
    method: string,
    path: string,
    body?: unknown,
    isRetry = false,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        credentials: 'include', // send/receive the httpOnly auth cookies
        headers: this.getHeaders(method),
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw new Error('Request timed out. Please try again.');
      }
      throw err;
    } finally {
      clearTimeout(timeout);
    }

    // On a 401, try a one-shot token refresh then replay the request. This is
    // what lets a hard page-reload with an expired (but refreshable) access
    // cookie recover on the FIRST load instead of requiring a second refresh.
    //
    // Endpoints where a 401 is terminal (bad credentials, not an expired
    // session) must NOT retry: login and the 2FA verify. `/auth/refresh` itself
    // is issued via a raw fetch (see refreshToken) so it never reaches here.
    if (
      response.status === 401 &&
      !isRetry &&
      !NO_REFRESH_RETRY_PATHS.some((p) => path.startsWith(p))
    ) {
      const refreshed = await this.refreshToken();
      if (refreshed) {
        return this.request(method, path, body, true);
      }
      this.onSessionExpired?.();
    }

    return this.handleResponse(response);
  }

  private get(path: string) {
    return this.request('GET', path);
  }

  private post(path: string, data?: unknown) {
    return this.request('POST', path, data);
  }

  private patch(path: string, data?: unknown) {
    return this.request('PATCH', path, data);
  }

  private put(path: string, data?: unknown) {
    return this.request('PUT', path, data);
  }

  private del(path: string, data?: unknown) {
    return this.request('DELETE', path, data);
  }

  /**
   * Escape hatch for optional feature modules (e.g. the Enterprise console)
   * that live outside this file and must not hardcode their own fetch/CSRF/
   * refresh handling. It shares this client's single HTTP pipeline while
   * keeping their endpoint paths out of the core, Community-shipped api.ts.
   */
  raw(method: string, path: string, data?: unknown) {
    return this.request(method, path, data);
  }

  // Auth
  //
  // Tokens are never handled by JavaScript: the backend sets them as httpOnly
  // cookies on these responses, so an XSS payload cannot read or exfiltrate a
  // session. The body only carries the user object and a CSRF token.
  async login(credentials: LoginCredentials): Promise<LoginResponse> {
    return this.post('/api/v1/auth/login', credentials) as Promise<LoginResponse>;
  }

  async verify2FA(code: string): Promise<LoginResponse> {
    // The pending-2FA challenge is itself an httpOnly cookie set at login.
    return this.post('/api/v1/auth/2fa/verify', { code }) as Promise<LoginResponse>;
  }

  async logout(): Promise<void> {
    try {
      // Server-side: clears cookies and deny-lists the tokens.
      await this.post('/api/v1/auth/logout');
    } catch {
      // Already signed out or unreachable — the cookies expire regardless.
    }
  }

  async getCurrentUser(): Promise<User> {
    return this.get('/api/v1/auth/me') as Promise<User>;
  }

  // Tenants
  async registerTenant(data: TenantRegistration): Promise<TenantRegistrationResponse> {
    return this.post('/api/v1/tenants/register', data) as Promise<TenantRegistrationResponse>;
  }

  async checkSlug(slug: string): Promise<SlugCheckResponse> {
    return this.get(`/api/v1/tenants/check-slug/${slug}`) as Promise<SlugCheckResponse>;
  }

  async getSetupStatus(): Promise<{ steps: Array<{ key: string; label: string; done: boolean; count: number; link: string }>; completed: number; total: number }> {
    return this.get('/api/v1/tenants/setup-status') as Promise<{ steps: Array<{ key: string; label: string; done: boolean; count: number; link: string }>; completed: number; total: number }>;
  }

  async getCurrentTenant(): Promise<Tenant> {
    return this.get('/api/v1/tenants/current') as Promise<Tenant>;
  }

  async updateTenant(data: unknown): Promise<Tenant> {
    return this.patch('/api/v1/tenants/current', data) as Promise<Tenant>;
  }

  async updateTenantBranding(data: unknown): Promise<Tenant> {
    return this.patch('/api/v1/tenants/current/branding', data) as Promise<Tenant>;
  }

  async getTenantStats(): Promise<TenantStats> {
    return this.get('/api/v1/tenants/current/stats') as Promise<TenantStats>;
  }

  // Users
  async getUsers(params?: Record<string, string>): Promise<PaginatedResponse<User>> {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/users${query}`) as Promise<PaginatedResponse<User>>;
  }

  async createUser(data: unknown): Promise<User> {
    return this.post('/api/v1/users', data) as Promise<User>;
  }

  async getUser(id: number): Promise<User> {
    return this.get(`/api/v1/users/${id}`) as Promise<User>;
  }

  async updateUser(id: number, data: unknown): Promise<User> {
    return this.patch(`/api/v1/users/${id}`, data) as Promise<User>;
  }

  async deleteUser(id: number): Promise<void> {
    await this.del(`/api/v1/users/${id}`);
  }

  async separateUser(id: number, data: { separation_type: string; separation_date: string; separation_reason?: string }): Promise<User> {
    return this.post(`/api/v1/users/${id}/separate`, data) as Promise<User>;
  }

  async reinstateUser(id: number): Promise<User> {
    return this.post(`/api/v1/users/${id}/reinstate`) as Promise<User>;
  }

  async resendInvite(userId: number): Promise<{ message: string }> {
    return this.post(`/api/v1/users/${userId}/resend-invite`) as Promise<{ message: string }>;
  }

  async validateInviteToken(token: string): Promise<{ valid: boolean; email?: string; first_name?: string; tenant_name?: string }> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/validate-invite-token?token=${encodeURIComponent(token)}`);
    if (!response.ok) {
      return { valid: false };
    }
    return response.json();
  }

  async activateAccount(token: string, newPassword: string): Promise<{ message: string }> {
    const response = await fetch(`${this.baseUrl}/api/v1/auth/activate-account`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!response.ok) {
      let detail = 'Activation failed';
      try {
        const data = await response.json();
        detail = data.detail || detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return response.json();
  }

  async updateMyProfile(data: unknown): Promise<User> {
    return this.patch('/api/v1/users/me', data) as Promise<User>;
  }

  async changePassword(data: { current_password: string; new_password: string }): Promise<void> {
    await this.post('/api/v1/auth/change-password', data);
  }

  // Schedules
  async getScheduleGrid(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/schedules/grid${query}`);
  }

  async createShift(data: unknown) {
    return this.post('/api/v1/schedules/shifts', data);
  }

  async updateShift(id: number, data: unknown) {
    return this.patch(`/api/v1/schedules/shifts/${id}`, data);
  }

  async deleteShift(id: number) {
    return this.del(`/api/v1/schedules/shifts/${id}`);
  }

  async exportSchedule(params: Record<string, string>): Promise<Blob> {
    const query = '?' + new URLSearchParams(params).toString();
    const response = await fetch(`${this.baseUrl}/api/v1/schedules/export${query}`, {
      credentials: 'include',
      headers: this.getHeaders('GET'),
    });
    return response.blob();
  }

  async exportScheduleXlsx(params: Record<string, string>): Promise<Blob> {
    const query = '?' + new URLSearchParams(params).toString();
    const response = await fetch(`${this.baseUrl}/api/v1/schedules/export.xlsx${query}`, {
      credentials: 'include',
      headers: this.getHeaders('GET'),
    });
    if (!response.ok) throw new Error('Export failed');
    return response.blob();
  }

  async copyShifts(data: unknown) {
    return this.post('/api/v1/schedules/copy', data);
  }

  async getDateRemarks(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/schedules/date-remarks${query}`);
  }

  async createDateRemark(data: unknown) {
    return this.post('/api/v1/schedules/date-remarks', data);
  }

  async updateDateRemark(id: number, data: unknown) {
    return this.patch(`/api/v1/schedules/date-remarks/${id}`, data);
  }

  async deleteDateRemark(id: number) {
    return this.del(`/api/v1/schedules/date-remarks/${id}`);
  }

  async getHolidays(year?: number) {
    const query = year ? `?year=${year}` : '';
    return this.get(`/api/v1/schedules/holidays${query}`);
  }

  async getTemplates() {
    return this.get('/api/v1/schedules/templates');
  }

  async createTemplate(data: unknown) {
    return this.post('/api/v1/schedules/templates', data);
  }

  async applyTemplate(id: number, data: unknown) {
    return this.post(`/api/v1/schedules/templates/${id}/apply`, data);
  }

  async bulkCreateShifts(data: unknown): Promise<ShiftBulkCreateResult> {
    return this.post('/api/v1/schedules/shifts/bulk', data) as Promise<ShiftBulkCreateResult>;
  }

  async bulkDeleteShifts(data: { start_date: string; end_date: string; employee_ids?: number[] }): Promise<{ deleted_count: number }> {
    return this.post('/api/v1/schedules/shifts/bulk-delete', data) as Promise<{ deleted_count: number }>;
  }

  // Schedule Snapshots
  async getSnapshots(): Promise<ScheduleSnapshot[]> {
    return this.get('/api/v1/schedules/snapshots') as Promise<ScheduleSnapshot[]>;
  }

  async createSnapshot(data: { name: string; description?: string; start_date: string; end_date: string; range_type: string }): Promise<ScheduleSnapshot> {
    return this.post('/api/v1/schedules/snapshots', data) as Promise<ScheduleSnapshot>;
  }

  async previewSnapshotApply(
    id: number,
    data: { target_start_date: string; repeat_until?: string; employee_ids?: number[] },
  ): Promise<SnapshotPreview> {
    return this.post(`/api/v1/schedules/snapshots/${id}/preview`, data) as Promise<SnapshotPreview>;
  }

  async applySnapshot(
    id: number,
    data: {
      target_start_date: string;
      repeat_until?: string;
      employee_ids?: number[];
      on_conflict?: 'skip' | 'overwrite';
    },
  ): Promise<SnapshotApplyResult> {
    return this.post(`/api/v1/schedules/snapshots/${id}/apply`, data) as Promise<SnapshotApplyResult>;
  }

  async deleteSnapshot(id: number) {
    return this.del(`/api/v1/schedules/snapshots/${id}`);
  }

  // Copy week (reuses snapshot preview/apply response shapes)
  async copyWeekPreview(data: {
    source_start_date: string;
    source_end_date: string;
    target_start_date?: string;
    employee_ids?: number[];
    on_conflict?: 'skip' | 'overwrite';
  }): Promise<SnapshotPreview> {
    return this.post('/api/v1/schedules/copy-week/preview', data) as Promise<SnapshotPreview>;
  }

  async copyWeek(data: {
    source_start_date: string;
    source_end_date: string;
    target_start_date?: string;
    employee_ids?: number[];
    on_conflict?: 'skip' | 'overwrite';
  }): Promise<SnapshotApplyResult> {
    return this.post('/api/v1/schedules/copy-week', data) as Promise<SnapshotApplyResult>;
  }

  // Guardrail lint (inline warnings)
  async lintSchedule(data: {
    start_date: string;
    end_date: string;
    employee_ids?: number[];
  }): Promise<{ violations: ScheduleLintViolation[] }> {
    return this.post('/api/v1/schedules/lint', data) as Promise<{ violations: ScheduleLintViolation[] }>;
  }

  // Draft / publish
  async publishSchedule(data: {
    start_date: string;
    end_date: string;
    employee_ids?: number[];
  }): Promise<{ published_count: number; notified: number }> {
    return this.post('/api/v1/schedules/publish', data) as Promise<{ published_count: number; notified: number }>;
  }

  async unpublishSchedule(data: {
    start_date: string;
    end_date: string;
    employee_ids?: number[];
  }): Promise<{ unpublished_count: number }> {
    return this.post('/api/v1/schedules/unpublish', data) as Promise<{ unpublished_count: number }>;
  }

  // Schedule Change Requests
  async createScheduleChangeRequest(data: {
    request_type: 'swap' | 'change';
    date: string;
    end_date?: string;
    target_employee_id?: number;
    requested_start_time?: string;
    requested_end_time?: string;
    requested_status?: string;
    requested_work_arrangement?: string;
    reason?: string;
  }): Promise<ScheduleChangeRequest> {
    return this.post('/api/v1/schedules/change-requests', data) as Promise<ScheduleChangeRequest>;
  }

  async getMyScheduleChangeRequests(): Promise<ScheduleChangeRequest[]> {
    return this.get('/api/v1/schedules/change-requests') as Promise<ScheduleChangeRequest[]>;
  }

  async getPendingScheduleApprovals(): Promise<ScheduleChangeRequest[]> {
    return this.get('/api/v1/schedules/change-requests/pending-approvals') as Promise<ScheduleChangeRequest[]>;
  }

  async getScheduleChangeRequest(id: number): Promise<ScheduleChangeRequest> {
    return this.get(`/api/v1/schedules/change-requests/${id}`) as Promise<ScheduleChangeRequest>;
  }

  async reviewScheduleChangeRequest(id: number, data: { action: 'approve' | 'reject'; notes?: string }): Promise<ScheduleChangeRequest> {
    return this.post(`/api/v1/schedules/change-requests/${id}/review`, data) as Promise<ScheduleChangeRequest>;
  }

  async cancelScheduleChangeRequest(id: number): Promise<ScheduleChangeRequest> {
    return this.post(`/api/v1/schedules/change-requests/${id}/cancel`) as Promise<ScheduleChangeRequest>;
  }

  // Settings
  async getAppSettings(): Promise<AppSettings> {
    return this.get('/api/v1/settings/app') as Promise<AppSettings>;
  }

  async updateAppSettings(data: Partial<AppSettings>): Promise<AppSettings> {
    return this.patch('/api/v1/settings/app', data) as Promise<AppSettings>;
  }

  async getStatusTypes(): Promise<ShiftStatusType[]> {
    return this.get('/api/v1/settings/status-types') as Promise<ShiftStatusType[]>;
  }

  async createStatusType(data: unknown): Promise<ShiftStatusType> {
    return this.post('/api/v1/settings/status-types', data) as Promise<ShiftStatusType>;
  }

  async updateStatusType(id: number, data: unknown): Promise<ShiftStatusType> {
    return this.patch(`/api/v1/settings/status-types/${id}`, data) as Promise<ShiftStatusType>;
  }

  async deleteStatusType(id: number): Promise<void> {
    await this.del(`/api/v1/settings/status-types/${id}`);
  }

  // User Preferences
  async getUserPreferences(): Promise<UserPreferences> {
    return this.get('/api/v1/settings/preferences') as Promise<UserPreferences>;
  }

  async updateUserPreferences(data: Record<string, unknown>): Promise<UserPreferences> {
    return this.patch('/api/v1/settings/preferences', data) as Promise<UserPreferences>;
  }

  // Leave
  async getLeaveApplications(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/leave/applications${query}`);
  }

  async createLeaveApplication(data: unknown) {
    return this.post('/api/v1/leave/applications', data);
  }

  async getLeaveApplication(id: number) {
    return this.get(`/api/v1/leave/applications/${id}`);
  }

  async updateLeaveApplication(id: number, data: unknown) {
    return this.patch(`/api/v1/leave/applications/${id}`, data);
  }

  async reviewLeaveApplication(id: number, data: unknown) {
    return this.post(`/api/v1/leave/applications/${id}/approve`, data);
  }

  async getMyLeaveBalance(): Promise<LeaveBalance> {
    return this.get('/api/v1/leave/balance') as Promise<LeaveBalance>;
  }

  // Leave Types (configuration)
  async getLeaveTypes(): Promise<LeaveTypeConfig[]> {
    return this.get('/api/v1/leave/types') as Promise<LeaveTypeConfig[]>;
  }

  async createLeaveType(data: { code: string; name: string; description?: string; sort_order?: number }): Promise<LeaveTypeConfig> {
    return this.post('/api/v1/leave/types', data) as Promise<LeaveTypeConfig>;
  }

  async updateLeaveType(id: number, data: { name?: string; description?: string; is_active?: boolean; sort_order?: number }): Promise<LeaveTypeConfig> {
    return this.patch(`/api/v1/leave/types/${id}`, data) as Promise<LeaveTypeConfig>;
  }

  async deleteLeaveType(id: number): Promise<void> {
    await this.del(`/api/v1/leave/types/${id}`);
  }

  // Leave Policies
  async getLeavePolicies(): Promise<LeavePolicy[]> {
    return this.get('/api/v1/leave/policies') as Promise<LeavePolicy[]>;
  }

  async getLeavePolicy(id: number): Promise<LeavePolicy> {
    return this.get(`/api/v1/leave/policies/${id}`) as Promise<LeavePolicy>;
  }

  async createLeavePolicy(data: unknown): Promise<LeavePolicy> {
    return this.post('/api/v1/leave/policies', data) as Promise<LeavePolicy>;
  }

  async updateLeavePolicy(id: number, data: unknown): Promise<LeavePolicy> {
    return this.patch(`/api/v1/leave/policies/${id}`, data) as Promise<LeavePolicy>;
  }

  async deleteLeavePolicy(id: number): Promise<void> {
    await this.del(`/api/v1/leave/policies/${id}`);
  }

  async cloneLeavePolicy(id: number): Promise<LeavePolicy> {
    return this.post(`/api/v1/leave/policies/${id}/clone`, {}) as Promise<LeavePolicy>;
  }

  async previewApprovalChain(employeeId: number): Promise<{ chain: Array<{ approver_id: number; approver_name: string; step_order: number; source: string }> }> {
    return this.get(`/api/v1/leave/approval-chain-preview?employee_id=${employeeId}`) as Promise<{ chain: Array<{ approver_id: number; approver_name: string; step_order: number; source: string }> }>;
  }

  async precheckLeave(data: { leave_type: string; start_date: string; end_date: string; supporting_documents?: string[] }): Promise<{ allowed: boolean; days_requested: number; violations: Array<{ rule: string; mode: string; message: string }>; warnings: Array<{ rule: string; mode: string; message: string }> }> {
    return this.post('/api/v1/leave/applications/precheck', data) as Promise<{ allowed: boolean; days_requested: number; violations: Array<{ rule: string; mode: string; message: string }>; warnings: Array<{ rule: string; mode: string; message: string }> }>;
  }

  // Policy Entitlements
  async addPolicyEntitlement(policyId: number, data: unknown): Promise<LeavePolicyEntitlement> {
    return this.post(`/api/v1/leave/policies/${policyId}/entitlements`, data) as Promise<LeavePolicyEntitlement>;
  }

  async updatePolicyEntitlement(policyId: number, entitlementId: number, data: unknown): Promise<LeavePolicyEntitlement> {
    return this.patch(`/api/v1/leave/policies/${policyId}/entitlements/${entitlementId}`, data) as Promise<LeavePolicyEntitlement>;
  }

  async deletePolicyEntitlement(policyId: number, entitlementId: number): Promise<void> {
    await this.del(`/api/v1/leave/policies/${policyId}/entitlements/${entitlementId}`);
  }

  async bulkReplacePolicyEntitlements(policyId: number, entitlements: unknown[]): Promise<LeavePolicyEntitlement[]> {
    return this.put(`/api/v1/leave/policies/${policyId}/entitlements`, { entitlements }) as Promise<LeavePolicyEntitlement[]>;
  }

  // Leave Approvals & Team
  async getPendingApprovals(params?: Record<string, string>): Promise<PaginatedResponse<LeaveApplication>> {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/leave/pending-approvals${query}`) as Promise<PaginatedResponse<LeaveApplication>>;
  }

  async getTeamStats(): Promise<TeamStats> {
    return this.get('/api/v1/leave/team-stats') as Promise<TeamStats>;
  }

  async getMyApprovalChain(): Promise<{ chain: ApprovalChainPreviewItem[] }> {
    return this.get('/api/v1/leave/my-approval-chain') as Promise<{ chain: ApprovalChainPreviewItem[] }>;
  }

  async cancelLeaveApplication(id: number): Promise<LeaveApplication> {
    return this.post(`/api/v1/leave/applications/${id}/cancel`) as Promise<LeaveApplication>;
  }

  // Approver Assignments
  async getApproverAssignments(): Promise<LeaveApproverAssignment[]> {
    return this.get('/api/v1/leave/approver-assignments') as Promise<LeaveApproverAssignment[]>;
  }

  async createApproverAssignment(data: unknown): Promise<LeaveApproverAssignment> {
    return this.post('/api/v1/leave/approver-assignments', data) as Promise<LeaveApproverAssignment>;
  }

  async updateApproverAssignment(id: number, data: unknown): Promise<LeaveApproverAssignment> {
    return this.patch(`/api/v1/leave/approver-assignments/${id}`, data) as Promise<LeaveApproverAssignment>;
  }

  async deleteApproverAssignment(id: number): Promise<void> {
    await this.del(`/api/v1/leave/approver-assignments/${id}`);
  }

  async reorderApproverAssignments(orderedIds: number[]): Promise<void> {
    await this.put('/api/v1/leave/approver-assignments/reorder', orderedIds);
  }

  // Overtime Categories
  async getOvertimeCategories(): Promise<OvertimeCategory[]> {
    return this.get('/api/v1/leave/overtime-categories') as Promise<OvertimeCategory[]>;
  }

  async createOvertimeCategory(data: unknown): Promise<OvertimeCategory> {
    return this.post('/api/v1/leave/overtime-categories', data) as Promise<OvertimeCategory>;
  }

  async updateOvertimeCategory(id: number, data: unknown): Promise<OvertimeCategory> {
    return this.patch(`/api/v1/leave/overtime-categories/${id}`, data) as Promise<OvertimeCategory>;
  }

  async deleteOvertimeCategory(id: number): Promise<void> {
    await this.del(`/api/v1/leave/overtime-categories/${id}`);
  }

  // Employee Types
  async getEmployeeTypes(): Promise<EmployeeTypeConfig[]> {
    return this.get('/api/v1/employee-types') as Promise<EmployeeTypeConfig[]>;
  }

  async getAllEmployeeTypes(): Promise<EmployeeTypeConfig[]> {
    return this.get('/api/v1/employee-types/all') as Promise<EmployeeTypeConfig[]>;
  }

  async createEmployeeType(data: { code: string; name: string; description?: string; sort_order?: number }): Promise<EmployeeTypeConfig> {
    return this.post('/api/v1/employee-types', data) as Promise<EmployeeTypeConfig>;
  }

  async updateEmployeeType(id: number, data: { name?: string; description?: string; is_active?: boolean; sort_order?: number }): Promise<EmployeeTypeConfig> {
    return this.patch(`/api/v1/employee-types/${id}`, data) as Promise<EmployeeTypeConfig>;
  }

  async deleteEmployeeType(id: number): Promise<void> {
    await this.del(`/api/v1/employee-types/${id}`);
  }

  // Schedule Formats
  async getScheduleFormats(): Promise<ScheduleFormatConfig[]> {
    return this.get('/api/v1/schedule-formats') as Promise<ScheduleFormatConfig[]>;
  }

  async getAllScheduleFormats(): Promise<ScheduleFormatConfig[]> {
    return this.get('/api/v1/schedule-formats/all') as Promise<ScheduleFormatConfig[]>;
  }

  async createScheduleFormat(data: { code: string; name: string; hours_per_day?: number; hours_per_week?: number; is_flexible?: boolean; paid_break_minutes?: number; unpaid_break_minutes?: number; paid_break_after_hours?: number; unpaid_break_after_hours?: number; description?: string; sort_order?: number }): Promise<ScheduleFormatConfig> {
    return this.post('/api/v1/schedule-formats', data) as Promise<ScheduleFormatConfig>;
  }

  async updateScheduleFormat(id: number, data: { name?: string; hours_per_day?: number; hours_per_week?: number; is_flexible?: boolean; paid_break_minutes?: number; unpaid_break_minutes?: number; paid_break_after_hours?: number; unpaid_break_after_hours?: number; description?: string; is_active?: boolean; sort_order?: number }): Promise<ScheduleFormatConfig> {
    return this.patch(`/api/v1/schedule-formats/${id}`, data) as Promise<ScheduleFormatConfig>;
  }

  async deleteScheduleFormat(id: number): Promise<void> {
    await this.del(`/api/v1/schedule-formats/${id}`);
  }

  // Secondary Org Node Members
  async assignSecondaryMembers(nodeId: number, userIds: number[]): Promise<{ assigned: number }> {
    return this.post(`/api/v1/organizations/nodes/${nodeId}/secondary-members`, { user_ids: userIds }) as Promise<{ assigned: number }>;
  }

  async removeSecondaryMembers(nodeId: number, userIds: number[]): Promise<{ removed: number }> {
    return this.del(`/api/v1/organizations/nodes/${nodeId}/secondary-members`, { user_ids: userIds }) as Promise<{ removed: number }>;
  }

  // Organizations (legacy)
  async getDepartments(params?: Record<string, string>): Promise<PaginatedResponse<Department>> {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/organizations/departments${query}`) as Promise<PaginatedResponse<Department>>;
  }

  async createDepartment(data: unknown) {
    return this.post('/api/v1/organizations/departments', data);
  }

  async getDivisions(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/organizations/divisions${query}`);
  }

  async getSections(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/organizations/sections${query}`);
  }

  async getUnits(params?: Record<string, string>) {
    const query = params ? '?' + new URLSearchParams(params).toString() : '';
    return this.get(`/api/v1/organizations/units${query}`);
  }

  // Org Hierarchy
  async getOrgLevels(): Promise<{ levels: OrgLevel[] }> {
    return this.get('/api/v1/organizations/levels') as Promise<{ levels: OrgLevel[] }>;
  }

  async setOrgLevels(levels: OrgLevelItem[]): Promise<{ levels: OrgLevel[] }> {
    return this.put('/api/v1/organizations/levels', { levels }) as Promise<{ levels: OrgLevel[] }>;
  }

  async getOrgTree(): Promise<OrgTreeResponse> {
    return this.get('/api/v1/organizations/tree') as Promise<OrgTreeResponse>;
  }

  async createOrgNode(data: {
    parent_id?: number | null;
    level_id: number;
    name: string;
    code?: string;
    description?: string;
    head_user_id?: number;
    deputy_head_user_id?: number;
    sort_order?: number;
  }): Promise<OrgNodeDetail> {
    return this.post('/api/v1/organizations/nodes', data) as Promise<OrgNodeDetail>;
  }

  async getOrgNode(id: number): Promise<OrgNodeDetail> {
    return this.get(`/api/v1/organizations/nodes/${id}`) as Promise<OrgNodeDetail>;
  }

  async updateOrgNode(id: number, data: Record<string, unknown>): Promise<OrgNodeDetail> {
    return this.patch(`/api/v1/organizations/nodes/${id}`, data) as Promise<OrgNodeDetail>;
  }

  async deleteOrgNode(id: number): Promise<void> {
    await this.del(`/api/v1/organizations/nodes/${id}`);
  }

  async getOrgNodeMembers(nodeId: number): Promise<OrgNodeMembersResponse> {
    return this.get(`/api/v1/organizations/nodes/${nodeId}/members`) as Promise<OrgNodeMembersResponse>;
  }

  async assignOrgNodeMembers(nodeId: number, userIds: number[]): Promise<{ assigned: number }> {
    return this.post(`/api/v1/organizations/nodes/${nodeId}/members`, { user_ids: userIds }) as Promise<{ assigned: number }>;
  }

  async unassignOrgNodeMembers(nodeId: number, userIds: number[]): Promise<{ unassigned: number }> {
    return this.del(`/api/v1/organizations/nodes/${nodeId}/members`, { user_ids: userIds }) as Promise<{ unassigned: number }>;
  }

  async getApprovalChain(userId: number): Promise<ApprovalChainResponse> {
    return this.get(`/api/v1/organizations/approval-chain/${userId}`) as Promise<ApprovalChainResponse>;
  }

  // Analytics
  async getDashboardMetrics(): Promise<DashboardMetrics> {
    return this.get('/api/v1/analytics/dashboard') as Promise<DashboardMetrics>;
  }

  async getOvertimeTrends(params: { year: number; status?: string; start_date?: string; end_date?: string }): Promise<OvertimeTrendsResponse> {
    const query = new URLSearchParams({ year: String(params.year) });
    if (params.status) query.set('status', params.status);
    if (params.start_date) query.set('start_date', params.start_date);
    if (params.end_date) query.set('end_date', params.end_date);
    return this.get(`/api/v1/analytics/overtime/trends?${query}`) as Promise<OvertimeTrendsResponse>;
  }

  async getOvertimePaidUnpaid(params: { year: number; status?: string; start_date?: string; end_date?: string }): Promise<OvertimePaidUnpaidResponse> {
    const query = new URLSearchParams({ year: String(params.year) });
    if (params.status) query.set('status', params.status);
    if (params.start_date) query.set('start_date', params.start_date);
    if (params.end_date) query.set('end_date', params.end_date);
    return this.get(`/api/v1/analytics/overtime/paid-vs-unpaid?${query}`) as Promise<OvertimePaidUnpaidResponse>;
  }

  async getLeaveTrends(params: { year: number; status?: string; start_date?: string; end_date?: string }): Promise<LeaveTrendsResponse> {
    const query = new URLSearchParams({ year: String(params.year) });
    if (params.status) query.set('status', params.status);
    if (params.start_date) query.set('start_date', params.start_date);
    if (params.end_date) query.set('end_date', params.end_date);
    return this.get(`/api/v1/analytics/leave/trends?${query}`) as Promise<LeaveTrendsResponse>;
  }

  async getAttendanceSummary(params: { year: number; start_date?: string; end_date?: string }): Promise<AttendanceSummaryResponse> {
    const query = new URLSearchParams({ year: String(params.year) });
    if (params.start_date) query.set('start_date', params.start_date);
    if (params.end_date) query.set('end_date', params.end_date);
    return this.get(`/api/v1/analytics/attendance/summary?${query}`) as Promise<AttendanceSummaryResponse>;
  }

  async getAnalyticsOverview(): Promise<AnalyticsOverviewResponse> {
    return this.get('/api/v1/analytics/overview') as Promise<AnalyticsOverviewResponse>;
  }

  // Site status (public)
  async getSiteStatus(): Promise<{ maintenance_mode: boolean; registration_enabled: boolean; site_name: string }> {
    return this.get('/api/v1/site/status') as Promise<{ maintenance_mode: boolean; registration_enabled: boolean; site_name: string }>;
  }

  // Enterprise console (site settings, SMTP, audit logs, backups, tenants)
  // deliberately does NOT live here — those endpoints are part of the paid
  // edition and its client lives in src/ee/, which the Community build omits.
  // See src/ee/superadminApi.ts.

  // Payroll - Salary Grades
  async getSalaryGrades(): Promise<SalaryGrade[]> {
    return this.get('/api/v1/payroll/salary-grades') as Promise<SalaryGrade[]>;
  }

  async getAllSalaryGrades(): Promise<SalaryGrade[]> {
    return this.get('/api/v1/payroll/salary-grades/all') as Promise<SalaryGrade[]>;
  }

  async createSalaryGrade(data: { code: string; name: string; monthly_rate: number; daily_rate?: number; hourly_rate?: number; description?: string; sort_order?: number }): Promise<SalaryGrade> {
    return this.post('/api/v1/payroll/salary-grades', data) as Promise<SalaryGrade>;
  }

  async updateSalaryGrade(id: number, data: Record<string, unknown>): Promise<SalaryGrade> {
    return this.patch(`/api/v1/payroll/salary-grades/${id}`, data) as Promise<SalaryGrade>;
  }

  async deleteSalaryGrade(id: number): Promise<void> {
    await this.del(`/api/v1/payroll/salary-grades/${id}`);
  }

  // Payroll - Employee Salary
  async assignEmployeeSalary(data: { employee_id: number; salary_grade_id: number; effective_date: string; monthly_rate_override?: number; notes?: string }): Promise<EmployeeSalaryAssignment> {
    return this.post('/api/v1/payroll/employee-salary', data) as Promise<EmployeeSalaryAssignment>;
  }

  async getEmployeeSalary(employeeId: number): Promise<EmployeeSalaryAssignment> {
    return this.get(`/api/v1/payroll/employee-salary/${employeeId}`) as Promise<EmployeeSalaryAssignment>;
  }

  async getEmployeeSalaryHistory(employeeId: number): Promise<EmployeeSalaryAssignment[]> {
    return this.get(`/api/v1/payroll/employee-salary/${employeeId}/history`) as Promise<EmployeeSalaryAssignment[]>;
  }

  // Payroll - Deduction Types
  async getDeductionTypes(): Promise<DeductionType[]> {
    return this.get('/api/v1/payroll/deduction-types') as Promise<DeductionType[]>;
  }

  async getAllDeductionTypes(): Promise<DeductionType[]> {
    return this.get('/api/v1/payroll/deduction-types/all') as Promise<DeductionType[]>;
  }

  async createDeductionType(data: { code: string; name: string; calculation_type?: string; default_amount?: number; default_rate?: number; is_mandatory?: boolean; is_employer_contribution?: boolean; description?: string; sort_order?: number }): Promise<DeductionType> {
    return this.post('/api/v1/payroll/deduction-types', data) as Promise<DeductionType>;
  }

  async updateDeductionType(id: number, data: Record<string, unknown>): Promise<DeductionType> {
    return this.patch(`/api/v1/payroll/deduction-types/${id}`, data) as Promise<DeductionType>;
  }

  async deleteDeductionType(id: number): Promise<void> {
    await this.del(`/api/v1/payroll/deduction-types/${id}`);
  }

  // Payroll - Periods
  async getPayrollPeriods(): Promise<PayrollPeriod[]> {
    return this.get('/api/v1/payroll/periods') as Promise<PayrollPeriod[]>;
  }

  async createPayrollPeriod(data: { name: string; period_type?: string; start_date: string; end_date: string; payout_date?: string; schedule_id?: number; notes?: string }): Promise<PayrollPeriod> {
    return this.post('/api/v1/payroll/periods', data) as Promise<PayrollPeriod>;
  }

  async computePayroll(periodId: number): Promise<PayrollPeriod> {
    return this.post(`/api/v1/payroll/periods/${periodId}/compute`) as Promise<PayrollPeriod>;
  }

  async approvePayroll(periodId: number): Promise<PayrollPeriod> {
    return this.post(`/api/v1/payroll/periods/${periodId}/approve`) as Promise<PayrollPeriod>;
  }

  async finalizePayroll(periodId: number): Promise<PayrollPeriod> {
    return this.post(`/api/v1/payroll/periods/${periodId}/finalize`) as Promise<PayrollPeriod>;
  }

  async getPayrollItems(periodId: number): Promise<PayrollItem[]> {
    return this.get(`/api/v1/payroll/periods/${periodId}/items`) as Promise<PayrollItem[]>;
  }

  async getPayrollSummary(periodId: number): Promise<PayrollSummary> {
    return this.get(`/api/v1/payroll/periods/${periodId}/summary`) as Promise<PayrollSummary>;
  }

  // ── Employee self-service payslips (own data only) ──────────────
  async getMyPayslips(): Promise<MyPayslipSummary[]> {
    return this.get('/api/v1/payroll/my-payslips') as Promise<MyPayslipSummary[]>;
  }

  async getMyPayslip(periodId: number): Promise<MyPayslipDetail> {
    return this.get(`/api/v1/payroll/my-payslips/${periodId}`) as Promise<MyPayslipDetail>;
  }

  // ── Compensation: payout schedules ──────────────────────────────
  async getPayoutSchedules(): Promise<PayoutSchedule[]> {
    return this.get('/api/v1/compensation/payout-schedules') as Promise<PayoutSchedule[]>;
  }

  async getActivePayoutSchedule(): Promise<PayoutSchedule | null> {
    return this.get('/api/v1/compensation/payout-schedules/active') as Promise<PayoutSchedule | null>;
  }

  async createPayoutSchedule(data: PayoutScheduleInput): Promise<PayoutSchedule> {
    return this.post('/api/v1/compensation/payout-schedules', data) as Promise<PayoutSchedule>;
  }

  async updatePayoutSchedule(id: number, data: Partial<PayoutScheduleInput>): Promise<PayoutSchedule> {
    return this.patch(`/api/v1/compensation/payout-schedules/${id}`, data) as Promise<PayoutSchedule>;
  }

  async deletePayoutSchedule(id: number): Promise<void> {
    await this.del(`/api/v1/compensation/payout-schedules/${id}`);
  }

  async previewPayoutDate(earned_on: string): Promise<{ earned_on: string; payout_date: string | null }> {
    return this.post('/api/v1/compensation/payout-schedules/preview', { earned_on }) as Promise<{ earned_on: string; payout_date: string | null }>;
  }

  // ── Compensation: items (bonus/incentive/allowance/…) ───────────
  async getCompensationItems(params?: { employee_id?: number; kind?: string; status?: string; date_from?: string; date_to?: string }): Promise<CompensationItem[]> {
    const qs = new URLSearchParams();
    if (params?.employee_id) qs.set('employee_id', String(params.employee_id));
    if (params?.kind) qs.set('kind', params.kind);
    if (params?.status) qs.set('status', params.status);
    if (params?.date_from) qs.set('date_from', params.date_from);
    if (params?.date_to) qs.set('date_to', params.date_to);
    const q = qs.toString();
    return this.get(`/api/v1/compensation/items${q ? `?${q}` : ''}`) as Promise<CompensationItem[]>;
  }

  async createCompensationItem(data: CompensationItemInput): Promise<CompensationItem> {
    return this.post('/api/v1/compensation/items', data) as Promise<CompensationItem>;
  }

  async bulkCreateCompensation(data: CompensationItemInput & { employee_ids: number[] }): Promise<CompensationItem[]> {
    return this.post('/api/v1/compensation/items/bulk', data) as Promise<CompensationItem[]>;
  }

  async voidCompensationItem(id: number, reason: string): Promise<CompensationItem> {
    return this.post(`/api/v1/compensation/items/${id}/void`, { reason }) as Promise<CompensationItem>;
  }

  async expandRecurringCompensation(horizon_start: string, horizon_end: string): Promise<{ created: number }> {
    return this.post('/api/v1/compensation/items/expand-recurring', { horizon_start, horizon_end }) as Promise<{ created: number }>;
  }

  // ── Compensation: salaries (central assign + raise) ─────────────
  async getCurrentSalaries(): Promise<CurrentSalaryRow[]> {
    return this.get('/api/v1/compensation/salaries') as Promise<CurrentSalaryRow[]>;
  }

  async assignSalary(data: { employee_id: number; salary_grade_id: number; effective_date: string; monthly_rate_override?: number; notes?: string }): Promise<CurrentSalaryRow> {
    return this.post('/api/v1/compensation/salaries', data) as Promise<CurrentSalaryRow>;
  }

  async giveRaise(data: { employee_ids: number[]; mode: 'percent' | 'fixed' | 'grade'; value?: number; effective_date: string; new_grade_id?: number; reason?: string }): Promise<RaiseResultRow[]> {
    return this.post('/api/v1/compensation/salaries/raise', data) as Promise<RaiseResultRow[]>;
  }

  // Permissions
  async getMyPermissions(): Promise<MyPermissionsResponse> {
    return this.get('/api/v1/permissions/me') as Promise<MyPermissionsResponse>;
  }

  async getPermissionMatrix(): Promise<PermissionMatrixResponse> {
    return this.get('/api/v1/permissions/matrix') as Promise<PermissionMatrixResponse>;
  }

  async updateRolePermissions(roleId: number, permissions: { module: string; can_view: boolean; can_create: boolean; can_edit: boolean; can_delete: boolean; extra_permissions?: Record<string, boolean> }[]): Promise<void> {
    await this.put(`/api/v1/permissions/role/${roleId}`, { permissions });
  }

  // Attendance
  async recordAttendance(data: { employee_id: number; date: string; actual_start_time?: string; actual_end_time?: string; notes?: string }): Promise<AttendanceRecord> {
    return this.post('/api/v1/attendance', data) as Promise<AttendanceRecord>;
  }

  async listAttendance(params?: { employee_id?: number; start_date?: string; end_date?: string; status?: string; skip?: number; limit?: number }): Promise<AttendanceRecord[]> {
    const query = new URLSearchParams();
    if (params?.employee_id) query.set('employee_id', String(params.employee_id));
    if (params?.start_date) query.set('start_date', params.start_date);
    if (params?.end_date) query.set('end_date', params.end_date);
    if (params?.status) query.set('status', params.status);
    if (params?.skip) query.set('skip', String(params.skip));
    if (params?.limit) query.set('limit', String(params.limit));
    const qs = query.toString();
    return this.get(`/api/v1/attendance${qs ? '?' + qs : ''}`) as Promise<AttendanceRecord[]>;
  }

  async getAttendance(id: number): Promise<AttendanceRecord> {
    return this.get(`/api/v1/attendance/${id}`) as Promise<AttendanceRecord>;
  }

  async updateAttendance(id: number, data: Record<string, unknown>): Promise<AttendanceRecord> {
    return this.put(`/api/v1/attendance/${id}`, data) as Promise<AttendanceRecord>;
  }

  // Overtime
  async listOvertimeLogs(params?: { employee_id?: number; status?: string; skip?: number; limit?: number }): Promise<OvertimeLog[]> {
    const query = new URLSearchParams();
    if (params?.employee_id) query.set('employee_id', String(params.employee_id));
    if (params?.status) query.set('status', params.status);
    if (params?.skip) query.set('skip', String(params.skip));
    if (params?.limit) query.set('limit', String(params.limit));
    const qs = query.toString();
    return this.get(`/api/v1/attendance/overtime${qs ? '?' + qs : ''}`) as Promise<OvertimeLog[]>;
  }

  async approveOvertime(logId: number, notes?: string): Promise<OvertimeLog> {
    return this.post(`/api/v1/attendance/overtime/${logId}/approve`, { notes }) as Promise<OvertimeLog>;
  }

  async rejectOvertime(logId: number, notes?: string): Promise<OvertimeLog> {
    return this.post(`/api/v1/attendance/overtime/${logId}/reject`, { notes }) as Promise<OvertimeLog>;
  }

  async convertOvertimeToLeave(logId: number, data?: { leave_type?: string; notes?: string }): Promise<OvertimeLog> {
    return this.post(`/api/v1/attendance/overtime/${logId}/convert`, data ?? {}) as Promise<OvertimeLog>;
  }

  // Tardiness
  async listTardinessRecords(params?: { employee_id?: number; resolution_type?: string; skip?: number; limit?: number }): Promise<TardinessRecord[]> {
    const query = new URLSearchParams();
    if (params?.employee_id) query.set('employee_id', String(params.employee_id));
    if (params?.resolution_type) query.set('resolution_type', params.resolution_type);
    if (params?.skip) query.set('skip', String(params.skip));
    if (params?.limit) query.set('limit', String(params.limit));
    const qs = query.toString();
    return this.get(`/api/v1/attendance/tardiness${qs ? '?' + qs : ''}`) as Promise<TardinessRecord[]>;
  }

  async resolveTardiness(recordId: number, data: { resolution_type: string; deduction_amount?: number; leave_type?: string; notes?: string }): Promise<TardinessRecord> {
    return this.post(`/api/v1/attendance/tardiness/${recordId}/resolve`, data) as Promise<TardinessRecord>;
  }

  // Policy Rules
  async listPolicyRules(params?: { rule_type?: string; active_only?: boolean }): Promise<PolicyRule[]> {
    const query = new URLSearchParams();
    if (params?.rule_type) query.set('rule_type', params.rule_type);
    if (params?.active_only !== undefined) query.set('active_only', String(params.active_only));
    const qs = query.toString();
    return this.get(`/api/v1/policy-rules${qs ? '?' + qs : ''}`) as Promise<PolicyRule[]>;
  }

  async getPolicyRule(id: number): Promise<PolicyRule> {
    return this.get(`/api/v1/policy-rules/${id}`) as Promise<PolicyRule>;
  }

  async createPolicyRule(data: Record<string, unknown>): Promise<PolicyRule> {
    return this.post('/api/v1/policy-rules', data) as Promise<PolicyRule>;
  }

  async updatePolicyRule(id: number, data: Record<string, unknown>): Promise<PolicyRule> {
    return this.put(`/api/v1/policy-rules/${id}`, data) as Promise<PolicyRule>;
  }

  async deletePolicyRule(id: number): Promise<void> {
    await this.del(`/api/v1/policy-rules/${id}`);
  }

  async simulatePolicyRules(data: { start_date: string; end_date: string; employee_ids?: number[] }): Promise<PolicySimulateResult> {
    return this.post('/api/v1/policy-rules/simulate', data) as Promise<PolicySimulateResult>;
  }

  // Data Export
  async getDataSources(): Promise<DataSource[]> {
    return this.get('/api/v1/data-export/sources') as Promise<DataSource[]>;
  }

  async getExportConfigs(): Promise<DataExportConfig[]> {
    return this.get('/api/v1/data-export/configs') as Promise<DataExportConfig[]>;
  }

  async getExportConfig(id: number): Promise<DataExportConfig> {
    return this.get(`/api/v1/data-export/configs/${id}`) as Promise<DataExportConfig>;
  }

  async createExportConfig(data: { name: string; description?: string; data_source: string; columns: string[]; custom_columns?: CustomColumn[]; filters?: FilterCondition[]; sort_by?: string; sort_direction?: string; name_format?: string }): Promise<DataExportConfig> {
    return this.post('/api/v1/data-export/configs', data) as Promise<DataExportConfig>;
  }

  async updateExportConfig(id: number, data: Record<string, unknown>): Promise<DataExportConfig> {
    return this.put(`/api/v1/data-export/configs/${id}`, data) as Promise<DataExportConfig>;
  }

  async deleteExportConfig(id: number): Promise<void> {
    await this.del(`/api/v1/data-export/configs/${id}`);
  }

  async previewExport(data: { data_source: string; columns: string[]; custom_columns?: CustomColumn[]; filters?: FilterCondition[]; sort_by?: string; sort_direction?: string }): Promise<PreviewResponse> {
    return this.post('/api/v1/data-export/preview', data) as Promise<PreviewResponse>;
  }

  async exportData(data: { data_source: string; columns: string[]; custom_columns?: CustomColumn[]; filters?: FilterCondition[]; sort_by?: string; sort_direction?: string }): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/api/v1/data-export/export`, {
      method: 'POST',
      credentials: 'include',
      headers: this.getHeaders('POST'),
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      let detail = 'Export failed';
      try {
        const err = await response.json();
        detail = err.detail || detail;
      } catch { /* ignore */ }
      throw new Error(detail);
    }
    return response.blob();
  }

  // Scheduled Exports
  async getScheduledExports(): Promise<ScheduledExport[]> {
    return this.get('/api/v1/data-export/schedules') as Promise<ScheduledExport[]>;
  }

  async createScheduledExport(data: { export_config_id: number; schedule_type: string; schedule_day?: number; schedule_time: string; recipient_emails: string[]; is_active?: boolean }): Promise<ScheduledExport> {
    return this.post('/api/v1/data-export/schedules', data) as Promise<ScheduledExport>;
  }

  async updateScheduledExport(id: number, data: Record<string, unknown>): Promise<ScheduledExport> {
    return this.put(`/api/v1/data-export/schedules/${id}`, data) as Promise<ScheduledExport>;
  }

  async deleteScheduledExport(id: number): Promise<void> {
    await this.del(`/api/v1/data-export/schedules/${id}`);
  }

  async runScheduledExportNow(id: number): Promise<ScheduledExport> {
    return this.post(`/api/v1/data-export/schedules/${id}/run-now`, {}) as Promise<ScheduledExport>;
  }

  // Salary access enrollment + approval
  async getSalaryEnrollments(): Promise<SalaryEnrollmentRow[]> {
    return this.get('/api/v1/salary-enrollment/enrollments') as Promise<SalaryEnrollmentRow[]>;
  }

  async getSalaryRequests(status?: string): Promise<SalaryRequestRow[]> {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return this.get(`/api/v1/salary-enrollment/requests${q}`) as Promise<SalaryRequestRow[]>;
  }

  async getMySalaryStatus(): Promise<MySalaryStatus> {
    return this.get('/api/v1/salary-enrollment/my-status') as Promise<MySalaryStatus>;
  }

  async createSalaryRequest(data: { kind: string; reason?: string; user_id?: number }): Promise<SalaryRequestRow> {
    return this.post('/api/v1/salary-enrollment/requests', data) as Promise<SalaryRequestRow>;
  }

  async approveSalaryRequest(id: number, note?: string): Promise<SalaryRequestRow> {
    return this.post(`/api/v1/salary-enrollment/requests/${id}/approve`, { note }) as Promise<SalaryRequestRow>;
  }

  async declineSalaryRequest(id: number, note?: string): Promise<SalaryRequestRow> {
    return this.post(`/api/v1/salary-enrollment/requests/${id}/decline`, { note }) as Promise<SalaryRequestRow>;
  }

  async cancelSalaryRequest(id: number): Promise<void> {
    await this.post(`/api/v1/salary-enrollment/requests/${id}/cancel`, {});
  }

  async revokeSalaryEnrollment(userId: number, kind: string): Promise<void> {
    await this.post('/api/v1/salary-enrollment/enrollments/revoke', { user_id: userId, kind });
  }

  async getSalaryRequestByToken(token: string): Promise<SalaryRequestByToken> {
    return this.get(`/api/v1/salary-enrollment/requests/by-token?token=${encodeURIComponent(token)}`) as Promise<SalaryRequestByToken>;
  }

  // Notifications
  async getNotifications(unreadOnly = false): Promise<NotificationList> {
    const q = unreadOnly ? '?unread_only=true' : '';
    return this.get(`/api/v1/notifications${q}`) as Promise<NotificationList>;
  }

  async markNotificationRead(id: number): Promise<void> {
    await this.post(`/api/v1/notifications/${id}/read`, {});
  }

  async markAllNotificationsRead(): Promise<void> {
    await this.post('/api/v1/notifications/read-all', {});
  }
}

export const api = new ApiClient();
