export type RoleCode = 'employee' | 'tenant_admin' | 'hr' | 'manager' | 'leave_approver' | 'schedule_editor' | 'finance' | 'report_viewer';

export interface Role {
  id: number;
  code: RoleCode;
  name: string;
  description?: string;
  is_system: boolean;
  is_active: boolean;
}

export interface UserRoleAssignment {
  id: number;
  role: Role;
  title?: string;
  assigned_at?: string;
}

// Minimal employee record returned by GET /users/lookup, for pickers.
export interface UserLookup {
  id: number;
  name: string;
  email: string;
  username: string;
  personnel_number: string | null;
  org_node_id: number | null;
  is_active: boolean;
}

export interface User {
  id: number;
  tenant_id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar?: string;
  contact_number?: string;
  personnel_number?: string;
  typecode?: string;
  id_number?: string;
  hiring_date?: string;
  job_title?: string;
  rank?: string;
  div_department?: string;
  employee_type?: string;
  schedule_format?: string;
  section_id?: number;
  unit_id?: number;
  department_id?: number;
  division_id?: number;
  reports_to_id?: number;
  roles: UserRoleAssignment[];
  primary_role: string;
  is_superadmin?: boolean;
  is_active: boolean;
  separation_type?: string;
  separation_date?: string;
  separation_reason?: string;
  separated_by?: number;
  must_change_password?: boolean;
  created_at: string;
  updated_at: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

/**
 * Auth response. Access/refresh tokens are delivered as httpOnly cookies and
 * are deliberately absent from the body — JavaScript must not be able to read
 * them. `csrf_token` is echoed back in the X-CSRF-Token header on writes.
 */
export interface LoginResponse {
  expires_in: number;
  user: User | null;
  requires_2fa?: boolean;
  csrf_token?: string;
}

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  domain?: string;
  email: string;
  phone?: string;
  industry?: string;
  company_size?: string;
  country?: string;
  timezone?: string;
  plan: string;
  subscription_status: string;
  subscription_ends_at?: string;
  max_users: number;
  max_storage_gb: number;
  settings?: Record<string, unknown>;
  branding?: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TenantRegistration {
  organization_name: string;
  slug: string;
  admin_email: string;
  admin_password: string;
  admin_first_name: string;
  admin_last_name: string;
  industry?: string;
  company_size?: string;
  country?: string;
  timezone?: string;
}

export interface TenantRegistrationResponse {
  tenant: Tenant;
  admin_user: User;
  trial_ends_at: string;
}

export interface SlugCheckResponse {
  slug: string;
  available: boolean;
}

export interface Division {
  id: number;
  name: string;
  code?: string;
  department_id?: number;
  description?: string;
  is_active: boolean;
}

export interface Section {
  id: number;
  name: string;
  code?: string;
  division_id?: number;
  description?: string;
  is_active: boolean;
}

export interface Unit {
  id: number;
  name: string;
  code?: string;
  section_id?: number;
  description?: string;
  is_active: boolean;
}

export interface OrganizationTree {
  id: number;
  name: string;
  code: string;
  type: 'department' | 'division' | 'section' | 'unit';
  children?: OrganizationTree[];
}

// ShiftStatus is now a string to support tenant-defined custom statuses
export type ShiftStatus = string;

export type WorkArrangement = 'wfh' | 'onsite' | 'hybrid' | 'ob';

export interface Shift {
  id: number;
  employee_id: number;
  employee_name?: string;
  date: string;
  start_time?: string;
  end_time?: string;
  sequence_number: number;
  status: ShiftStatus;
  work_arrangement?: WorkArrangement;
  role_id?: number;
  role_name?: string;
  color?: string;
  notes?: string;
  remarks?: string;
  is_published?: boolean;
}

export interface ScheduleEmployee {
  employee_id: number;
  employee_name: string;
  section_name?: string;
  unit_name?: string;
  shifts: Shift[];
}

export interface ScheduleStats {
  total_shifts: number;
  total_employees: number;
  scheduled_count: number;
  leave_count: number;
  rest_day_count: number;
}

export interface ShiftActuals {
  employee_id: number;
  date: string;
  /** present | late | absent | half_day | excused */
  attendance_status?: string | null;
  tardiness_minutes: number;
  /** Approved overtime only. */
  overtime_minutes: number;
}

export interface ScheduleGrid {
  employees: ScheduleEmployee[];
  dates: string[];
  date_remarks: DateRemark[];
  stats: ScheduleStats;
  /** Empty unless the request set include_actuals=true. */
  actuals?: ShiftActuals[];
}

export interface DateRemark {
  id: number;
  date: string;
  title: string;
  description?: string;
  is_holiday: boolean;
  is_special: boolean;
  is_recurring: boolean;
}

export interface ScheduleTemplate {
  id: number;
  name: string;
  description?: string;
  template_data: Record<string, unknown>;
  is_active: boolean;
}

export interface AppSettings {
  timeclock_enabled?: boolean;
  timeclock_require_location?: boolean;
  timeclock_location_grace_minutes?: number;
  timeclock_default_radius_m?: number;
  id: number;
  timezone: string;
  currency_code: string;
  week_starts_on: 'monday' | 'sunday' | 'saturday';
  default_leave_days: number;
  default_shift_duration_hours: number;
  notify_on_leave_request: boolean;
  notify_on_leave_approval: boolean;
  notify_on_schedule_change: boolean;
  schedule_employee_visibility: 'all' | 'own_node' | 'own_and_children' | 'own_and_parent';
  // Payroll computation. Defaults are PH statutory; each install sets its own.
  working_days_per_month?: number;
  night_diff_multiplier?: number;
  night_shift_start?: string | null;   // "HH:MM:SS"; null = no night window
  night_shift_end?: string | null;
  holiday_worked_multiplier?: number;
  special_holiday_worked_multiplier?: number;
  // Schedule enforcement. 0 = rule disabled.
  max_consecutive_work_days?: number;
  min_rest_days_per_week?: number;
  auto_create_holiday_off?: boolean;
  data_retention_days?: number | null;
  analytics_exclusion_days?: number;
}

export interface SmtpSettings {
  smtp_active: boolean;
  smtp_host: string | null;
  smtp_port: number;
  smtp_use_ssl: boolean;
  smtp_use_tls: boolean;
  smtp_username: string | null;
  has_password: boolean;
  smtp_from_email: string | null;
  smtp_from_name: string | null;
}

export interface SmtpSettingsUpdate {
  smtp_active?: boolean;
  smtp_host?: string | null;
  smtp_port?: number;
  smtp_use_ssl?: boolean;
  smtp_use_tls?: boolean;
  smtp_username?: string | null;
  smtp_password?: string; // write-only; omit to keep current
  smtp_from_email?: string | null;
  smtp_from_name?: string | null;
}

export interface EmailLogEntry {
  id: number;
  type: string;
  to_email: string;
  subject: string;
  status: 'pending' | 'sent' | 'failed' | 'skipped';
  error_message?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
}

export interface ShiftStatusType {
  id: number;
  code: string;
  label: string;
  short_label: string;
  color: string;
  bg_class: string;
  category: 'work' | 'rest' | 'leave';
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
}

export interface UserPreferences {
  id: number;
  preferences: {
    schedule_row_order?: number[];
    schedule_timezone?: string;
    setup_checklist_dismissed?: boolean;
    [key: string]: unknown;
  };
  org_timezone?: string;
}

// ── Org Hierarchy ──────────────────────────────────────────────────

export interface OrgLevel {
  id: number;
  level_number: number;
  name: string;
}

export interface OrgLevelItem {
  level_number: number;
  name: string;
}

export interface OrgTreeNode {
  id: number;
  parent_id: number | null;
  level_id: number;
  level_name: string;
  level_number: number;
  name: string;
  code: string | null;
  head_user_id: number | null;
  head_user_name: string | null;
  deputy_head_user_id: number | null;
  deputy_head_user_name: string | null;
  member_count: number;
  is_active: boolean;
  children: OrgTreeNode[];
}

export interface OrgTreeResponse {
  levels: OrgLevel[];
  nodes: OrgTreeNode[];
}

export interface ScheduleVisibilityGrant {
  id: number;
  user_id: number;
  user_name: string | null;
  org_node_id: number;
  org_node_name: string | null;
  include_descendants: boolean;
  created_at: string | null;
}

export interface OrgNodeDetail {
  id: number;
  parent_id: number | null;
  level_id: number;
  level_name: string;
  name: string;
  code: string | null;
  description: string | null;
  head_user_id: number | null;
  head_user_name: string | null;
  deputy_head_user_id: number | null;
  deputy_head_user_name: string | null;
  sort_order: number;
  is_active: boolean;
  member_count: number;
  schedule_visibility: string | null;
}

export interface OrgNodeMember {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  job_title: string | null;
  avatar: string | null;
  is_primary: boolean;
}

export interface OrgNodeMembersResponse {
  node_id: number;
  node_name: string;
  members: OrgNodeMember[];
  total: number;
}

export interface AccessibleNode {
  id: number;
  parent_id: number | null;
  name: string;
  code: string | null;
  visible_member_count: number;
}

export interface AccessibleNodesResponse {
  can_see_all: boolean;
  nodes: AccessibleNode[];
}

export interface ApprovalChainStep {
  node_id: number;
  node_name: string;
  level_name: string;
  approver_id: number;
  approver_name: string;
  is_deputy: boolean;
}

export interface ApprovalChainResponse {
  employee_id: number;
  employee_name: string;
  chain: ApprovalChainStep[];
}

export type LeaveStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
export type AccrualMethod = 'monthly' | 'annual';
export type PoolType = 'per_type' | 'shared';
export type CompensationType = 'paid' | 'leave_credit' | 'both' | 'none';

// ── Configurable Types ──────────────────────────────────────────

export interface EmployeeTypeConfig {
  id: number;
  code: string;
  name: string;
  description?: string;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
}

export interface ScheduleFormatConfig {
  id: number;
  code: string;
  name: string;
  hours_per_day?: number;
  hours_per_week?: number;
  is_flexible: boolean;
  paid_break_minutes: number;
  unpaid_break_minutes: number;
  paid_break_after_hours: number;
  unpaid_break_after_hours: number;
  description?: string;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
}

export interface UserOrgNodeAssignment {
  id: number;
  user_id: number;
  org_node_id: number;
  org_node_name: string;
  is_primary: boolean;
  assigned_at: string;
}

export interface LeaveApprovalStep {
  id: number;
  step_order: number;
  approver_id: number;
  approver_name: string;
  status: 'pending' | 'approved' | 'rejected';
  decided_at?: string;
  notes?: string;
}

export type ApproverRole = 'node_head' | 'node_deputy' | 'parent_head' | 'parent_deputy';

export interface LeaveApproverAssignment {
  id: number;
  employee_id?: number;
  employee_name?: string;
  org_node_id?: number;
  org_node_name?: string;
  approver_id?: number;
  approver_name?: string;
  approver_role?: ApproverRole | null;
  step_order: number;
  priority: number;
  cascade: boolean;
  exclude: boolean;
  is_active: boolean;
}

export interface ApprovalChainPreviewItem {
  approver_id: number;
  approver_name: string;
  step_order: number;
  source: string;
}

export interface TeamStats {
  summary: { total: number; pending: number; approved: number; rejected: number };
  by_type: { leave_type: string; leave_type_name: string; count: number; days: number }[];
  by_month: { month: string; count: number; days: number }[];
  by_status: Record<string, number>;
}

export interface LeaveApplication {
  id: number;
  employee_id: number;
  employee_name: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  days_requested: number;
  reason: string;
  supporting_documents?: string[];
  status: LeaveStatus;
  reviewed_by?: number;
  reviewer_name?: string;
  reviewed_at?: string;
  reviewer_notes?: string;
  approval_steps: LeaveApprovalStep[];
  current_step?: number;
  created_at: string;
  updated_at: string;
}

export interface LeaveBalanceItem {
  leave_type: string;
  leave_type_name: string;
  total_days: number;
  used_days: number;
  pending_days: number;
  available_days: number;
}

export interface LeaveBalance {
  employee_id: number;
  policy_name?: string;
  accrual_method?: string;
  pool_type?: string;
  balances: LeaveBalanceItem[];
}

// ── Leave Type Configuration ─────────────────────────────────────

export interface LeaveTypeConfig {
  id: number;
  code: string;
  name: string;
  description?: string;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

// ── Leave Policy ─────────────────────────────────────────────────

export interface LeavePolicyEntitlement {
  id: number;
  leave_type_id: number;
  leave_type_code: string;
  leave_type_name: string;
  annual_credits: number;
  carry_over_enabled: boolean;
  max_carry_over_days: number;
  carry_over_expiry_months: number;
  cash_convertible: boolean;
  cash_conversion_rate: number;
  requires_documentation: boolean;
  min_notice_days: number;
  max_consecutive_days?: number | null;
}

export type EnforcementRule =
  | 'insufficient_balance'
  | 'min_notice_days'
  | 'max_consecutive_days'
  | 'overlapping_application'
  | 'requires_documentation';

export type EnforcementMode = 'block' | 'warn' | 'off';

export interface PolicyCompleteness {
  has_employment_types: boolean;
  has_entitlements: boolean;
  uncovered_leave_types: string[];
  has_approval_path: boolean;
  enforcement_configured: boolean;
}

export interface LeavePolicy {
  id: number;
  name: string;
  description?: string;
  accrual_method: AccrualMethod;
  pool_type: PoolType;
  employment_types: string[];
  is_default: boolean;
  is_active: boolean;
  approval_mode: 'auto' | 'manual' | 'hybrid';
  required_approval_levels: number;
  enforcement: Partial<Record<EnforcementRule, EnforcementMode>>;
  shared_annual_credits?: number;
  shared_carry_over_enabled: boolean;
  shared_max_carry_over_days: number;
  shared_carry_over_expiry_months: number;
  shared_cash_convertible: boolean;
  shared_cash_conversion_rate: number;
  shared_max_consecutive_days?: number | null;
  entitlements: LeavePolicyEntitlement[];
  completeness?: PolicyCompleteness;
  created_at: string;
  updated_at: string;
}

// ── Overtime Category ────────────────────────────────────────────

export interface OvertimeCategory {
  id: number;
  code: string;
  name: string;
  description?: string;
  multiplier_rate: number;
  compensation_type: CompensationType;
  leave_credit_rate?: number;
  leave_credit_type_id?: number;
  leave_credit_type_name?: string;
  is_active: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface DashboardLeaveItem {
  id: number;
  employee_name: string;
  leave_type: string;
  start_date: string;
  end_date: string;
  days: number;
  status: string;
}

export interface DashboardOvertimeItem {
  id: number;
  employee_name: string;
  category: string;
  date: string;
  hours: number;
  status: string;
}

export interface DashboardMetrics {
  total_employees: number;
  active_employees: number;
  departments: number;
  pending_leaves: number;
  pending_overtime: number;
  today_present: number;
  today_late: number;
  today_absent: number;
  month_attendance_rate: number;
  month_late_count: number;
  month_ot_hours: number;
  month_leave_days: number;
  recent_leave_applications: DashboardLeaveItem[];
  recent_overtime_logs: DashboardOvertimeItem[];
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// ── Superadmin ────────────────────────────────────────────────────

export interface SiteSettings {
  id: number;
  site_name: string;
  site_description?: string;
  site_timezone: string;
  primary_domain?: string;
  base_url?: string;
  allowed_domains?: string;
  support_email?: string;
  registration_enabled: boolean;
  maintenance_mode: boolean;
  smtp_active: boolean;
  smtp_host?: string;
  smtp_port: number;
  smtp_use_ssl: boolean;
  smtp_use_tls: boolean;
  smtp_username?: string;
  smtp_password?: string;
  smtp_from_email?: string;
  smtp_from_name?: string;
  smtp_admin_notification_email?: string;
  db_backup_enabled: boolean;
  db_backup_frequency: string;
  db_backup_time: string;
  db_backup_retention_days: number;
  db_backup_path?: string;
  app_backup_enabled: boolean;
  app_backup_frequency: string;
  app_backup_retention_days: number;
  app_backup_path?: string;
  notify_on_backup_failure: boolean;
  notification_email?: string;
}

export interface AuditLogEntry {
  id: number;
  tenant_id?: string;
  user_id?: number;
  user_email?: string;
  action: string;
  resource_type?: string;
  resource_id?: string;
  details?: Record<string, unknown>;
  ip_address?: string;
  user_agent?: string;
  created_at?: string;
}

export interface SmtpTestResult {
  success: boolean;
  message: string;
}

export interface BackupResult {
  success: boolean;
  message: string;
  file_path?: string;
}

export interface SuperadminTenant {
  id: string;
  name: string;
  slug: string;
  email: string;
  plan: string;
  subscription_status: string;
  is_active: boolean;
  created_at?: string;
  user_count: number;
}

// ── RBAC Permissions ─────────────────────────────────────────────

export type PermissionModule = 'employees' | 'organization' | 'schedules' | 'leave' | 'finances' | 'settings' | 'reports';
export type PermissionAction = 'view' | 'create' | 'edit' | 'delete';

export interface RolePermissionEntry {
  id: number;
  role_id: number;
  module: string;
  can_view: boolean;
  can_create: boolean;
  can_edit: boolean;
  can_delete: boolean;
  extra_permissions?: Record<string, boolean>;
}

export interface PermissionMatrixEntry {
  role_id: number;
  role_code: string;
  role_name: string;
  modules: Record<string, RolePermissionEntry>;
}

export interface PermissionMatrixResponse {
  entries: PermissionMatrixEntry[];
}

export interface MyPermissionsResponse {
  permissions: Record<string, Record<string, boolean>>;
  extra: Record<string, boolean>;
}

// ── Payroll ──────────────────────────────────────────────────────

export interface SalaryGrade {
  id: number;
  code: string;
  name: string;
  description?: string;
  /** Null (with rates_hidden) for anyone who is not a salary viewer. */
  monthly_rate: number | null;
  daily_rate?: number | null;
  hourly_rate?: number | null;
  rates_hidden?: boolean;
  is_active: boolean;
  sort_order: number;
  created_at?: string;
  updated_at?: string;
}

export interface EmployeeSalaryAssignment {
  id: number;
  employee_id: number;
  salary_grade_id: number;
  effective_date: string;
  monthly_rate_override?: number;
  notes?: string;
  grade_code?: string;
  grade_name?: string;
  grade_monthly_rate?: number;
  created_at?: string;
  updated_at?: string;
}

export type DeductionCalculationType = 'fixed' | 'percentage' | 'tiered';

export interface DeductionType {
  id: number;
  code: string;
  name: string;
  description?: string;
  calculation_type: DeductionCalculationType;
  default_amount?: number;
  default_rate?: number;
  is_mandatory: boolean;
  is_employer_contribution: boolean;
  is_system: boolean;
  is_active: boolean;
  sort_order: number;
  created_at?: string;
  updated_at?: string;
}

export type PayrollPeriodStatus = 'draft' | 'computing' | 'computed' | 'approved' | 'finalized';

export interface PayrollPeriod {
  id: number;
  name: string;
  period_type: string;
  start_date: string;
  end_date: string;
  status: PayrollPeriodStatus;
  computed_at?: string;
  computed_by?: number;
  approved_at?: string;
  approved_by?: number;
  finalized_at?: string;
  finalized_by?: number;
  notes?: string;
  item_count?: number;
  /** Null (with figures_hidden) for anyone who is not a salary viewer. */
  total_gross?: number | null;
  total_net?: number | null;
  figures_hidden?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface PayrollItem {
  id: number;
  payroll_period_id: number;
  employee_id: number;
  employee_name?: string;
  salary_grade_id?: number;
  grade_name?: string;
  base_pay: number;
  overtime_pay: number;
  gross_pay: number;
  total_deductions: number;
  total_contributions: number;
  net_pay: number;
  breakdown?: Record<string, unknown>;
  notes?: string;
  created_at?: string;
  updated_at?: string;
}

export interface PayrollSummary {
  period: PayrollPeriod;
  total_employees: number;
  total_base_pay: number;
  total_overtime_pay: number;
  total_gross_pay: number;
  total_deductions: number;
  total_contributions: number;
  total_net_pay: number;
  items: PayrollItem[];
}

// ── Attendance ──────────────────────────────────────────────────

export type AttendanceStatus = 'present' | 'late' | 'absent' | 'half_day' | 'excused';

export interface AttendanceRecord {
  id: number;
  tenant_id: string;
  employee_id: number;
  shift_id?: number;
  date: string;
  actual_start_time?: string;
  actual_end_time?: string;
  scheduled_start_time?: string;
  scheduled_end_time?: string;
  hours_worked?: number;
  tardiness_minutes: number;
  overtime_minutes: number;
  undertime_minutes: number;
  status: AttendanceStatus;
  notes?: string;
  recorded_by?: number;
  employee_name?: string;
  recorder_name?: string;
  created_at?: string;
  updated_at?: string;
}

export type OvertimeLogStatus = 'pending' | 'approved' | 'converted' | 'rejected';

export interface OvertimeLog {
  id: number;
  tenant_id: string;
  employee_id: number;
  attendance_record_id: number;
  date: string;
  overtime_minutes: number;
  overtime_category_id?: number;
  overtime_category_name?: string;
  pay_multiplier?: number;
  /** Null (with amount_hidden) for anyone who is not a salary viewer. */
  pay_amount?: number | null;
  amount_hidden?: boolean;
  leave_credits_earned?: number;
  status: OvertimeLogStatus;
  approved_by?: number;
  approved_at?: string;
  notes?: string;
  employee_name?: string;
  created_at?: string;
  updated_at?: string;
}

export type TardinessResolutionType = 'salary_deduction' | 'leave_deduction' | 'excused' | 'warning';

export interface TardinessRecord {
  id: number;
  tenant_id: string;
  employee_id: number;
  attendance_record_id: number;
  date: string;
  tardiness_minutes: number;
  resolution_type?: TardinessResolutionType;
  deduction_amount?: number;
  leave_credits_deducted?: number;
  policy_rule_id?: number;
  recorded_by?: number;
  notes?: string;
  employee_name?: string;
  created_at?: string;
  updated_at?: string;
}

export interface LeaveCreditAdjustment {
  id: number;
  tenant_id: string;
  employee_id: number;
  adjustment_type: string;
  leave_type?: string;
  credits: number;
  source_id?: number;
  source_type?: string;
  notes?: string;
  created_by?: number;
  employee_name?: string;
  created_at?: string;
}

// ── Policy Rules ────────────────────────────────────────────────

export type PolicyRuleType = 'overtime' | 'tardiness' | 'leave_conversion' | 'attendance';

export interface PolicyCondition {
  field: string;
  operator: string;
  value: unknown;
}

// A condition node is a leaf, or a group (all/any/not), nestable.
export interface PolicyConditionGroup {
  all?: PolicyConditionNode[];
  any?: PolicyConditionNode[];
  not?: PolicyConditionNode;
}
export type PolicyConditionNode = PolicyCondition | PolicyConditionGroup;
// Top-level: legacy flat list OR a single group node.
export type PolicyConditions = PolicyCondition[] | PolicyConditionGroup;

export interface PolicyBand {
  min?: number;
  max?: number;
  action: PolicyAction;
}

export interface PolicyAction {
  type: string;
  category_code?: string;
  round_to_hours?: number;
  deduction_rate?: number;
  leave_type?: string;
  start_hour?: number;
  end_hour?: number;
  convert_to_leave?: boolean;
  stop_processing?: boolean;
  // Range-band action: type === 'bands'
  field?: string;
  bands?: PolicyBand[];
}

export interface PolicyRule {
  id: number;
  tenant_id: string;
  name: string;
  description?: string;
  rule_type: PolicyRuleType;
  priority: number;
  is_active: boolean;
  conditions: PolicyConditions;
  actions: PolicyAction[];
  employment_types?: string[];
  scope_org_node_ids?: number[] | null;
  effective_from?: string | null;
  effective_until?: string | null;
  created_by?: number;
  created_at?: string;
  updated_at?: string;
}

export interface SimulatedEffect {
  employee_id: number;
  employee_name?: string;
  date: string;
  rule_id: number;
  rule_name: string;
  action: string;
  detail?: string;
}

export interface PolicySimulateResult {
  records_evaluated: number;
  effects: SimulatedEffect[];
}

// ── Data Export ─────────────────────────────────────────────────

export interface DataSourceColumn {
  key: string;
  label: string;
  type: string;
  is_salary?: boolean;
}

export interface DataSource {
  key: string;
  label: string;
  description: string;
  is_salary?: boolean;
  columns: DataSourceColumn[];
}

export interface CustomColumn {
  name: string;
  formula: string;
}

export interface FilterCondition {
  column: string;
  operator: string;
  value: unknown;
}

export interface DataExportConfig {
  id: number;
  tenant_id: string;
  name: string;
  description?: string;
  data_source: string;
  columns: string[];
  custom_columns: CustomColumn[];
  filters?: FilterCondition[];
  sort_by?: string;
  sort_direction?: string;
  name_format?: string;
  group_by?: string[];
  aggregations?: AggregationSpec[];
  column_aliases?: Record<string, string>;
  column_formats?: Record<string, ColumnFormat>;
  sorts?: SortSpec[];
  date_preset?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  output_format?: string;
  row_limit?: number | null;
  created_by?: number;
  created_at?: string;
  updated_at?: string;
}

export interface PreviewColumn {
  key: string;
  header: string;
}

export interface PreviewResponse {
  columns: string[];
  column_headers: PreviewColumn[];
  rows: Record<string, unknown>[];
  /** Rows matching the whole definition, before the preview limit. */
  total: number;
  returned: number;
  /** What a relative window like "last month" resolved to on the server. */
  resolved_date_from?: string | null;
  resolved_date_to?: string | null;
}

// ── Report builder ────────────────────────────────────────────────

export type AggregateFunc =
  | 'sum' | 'avg' | 'min' | 'max' | 'count' | 'count_distinct' | 'first';

export interface AggregationSpec {
  /** Empty for `count`, which counts rows rather than a column. */
  column: string;
  func: AggregateFunc;
  label?: string | null;
  /** Stable key the row is written under; kept out of the user's way. */
  output_key: string;
}

export interface SortSpec {
  column: string;
  direction: 'asc' | 'desc';
}

export interface ColumnFormat {
  kind: 'number' | 'date' | 'time' | 'text';
  pattern?: string;
  decimals?: number;
  thousands?: boolean;
  prefix?: string;
  suffix?: string;
  transform?: string;
}

export type DatePreset =
  | 'today' | 'yesterday' | 'last_7_days' | 'last_30_days' | 'last_90_days'
  | 'this_week' | 'last_week' | 'this_month' | 'last_month'
  | 'this_quarter' | 'this_year' | 'year_to_date' | 'custom';

/**
 * The whole definition of a report. Mirrors the backend spec exactly so the
 * builder, the preview, the download and a saved config cannot drift apart.
 */
export interface ExportSpec {
  data_source: string;
  columns: string[];
  custom_columns: CustomColumn[];
  filters: FilterCondition[];
  group_by: string[];
  aggregations: AggregationSpec[];
  column_aliases: Record<string, string>;
  column_formats: Record<string, ColumnFormat>;
  sorts: SortSpec[];
  date_preset?: DatePreset | null;
  date_from?: string | null;
  date_to?: string | null;
  output_format: 'csv' | 'xlsx';
  row_limit?: number | null;
  name_format?: string | null;
}

export interface ScheduledExport {
  id: number;
  tenant_id: string;
  export_config_id: number;
  export_config_name: string;
  schedule_type: 'daily' | 'weekly' | 'monthly';
  schedule_day?: number;
  schedule_time: string;
  recipient_emails: string[];
  is_active: boolean;
  last_run_at?: string;
  next_run_at?: string;
  last_run_status?: string;
  last_run_error?: string;
  created_by?: number;
  created_at?: string;
  updated_at?: string;
}

// ── Schedule Change Requests ─────────────────────────────────────────

export interface ScheduleChangeApprovalStep {
  id: number;
  step_order: number;
  step_type: 'peer_approval' | 'manager_approval';
  approver_id: number;
  approver_name: string;
  status: string;
  decided_at?: string;
  notes?: string;
}

export interface ScheduleSnapshot {
  id: number;
  name: string;
  description?: string;
  source_start_date: string;
  source_end_date: string;
  range_type: string;
  employee_count: number;
  shift_count: number;
  is_active: boolean;
  created_by?: number;
  created_at?: string;
}

export interface SnapshotOccurrence {
  index: number;
  start_date: string;
  end_date: string;
}

export interface SnapshotConflict {
  employee_id: number;
  employee_name: string;
  date: string;
  type: string; // approved_leave | existing_shift | max_consecutive_work_days | min_rest_days_per_week
  forceable: boolean;
  message: string;
  has_existing_shift: boolean;
}

export interface SnapshotPreview {
  occurrences: SnapshotOccurrence[];
  stride_days: number;
  total_shifts: number;
  create_count: number;
  blocking_conflicts: SnapshotConflict[]; // approved leave — always skipped
  resolvable_conflicts: SnapshotConflict[]; // user chooses skip vs overwrite
}

export interface SnapshotSkipped {
  employee_id: number;
  date: string;
  reason: string;
  message: string;
}

export interface SnapshotApplyResult {
  created: number;
  overwritten: number;
  skipped: SnapshotSkipped[];
}

export interface ScheduleChangeRequest {
  id: number;
  request_type: 'swap' | 'change';
  requester_id: number;
  requester_name: string;
  date: string;
  end_date?: string;
  target_employee_id?: number;
  target_employee_name?: string;
  original_start_time?: string;
  original_end_time?: string;
  original_status?: string;
  target_original_start_time?: string;
  target_original_end_time?: string;
  target_original_status?: string;
  requested_start_time?: string;
  requested_end_time?: string;
  requested_status?: string;
  requested_work_arrangement?: string;
  reason?: string;
  status: string;
  reviewed_by?: number;
  reviewer_name?: string;
  reviewed_at?: string;
  reviewer_notes?: string;
  approval_steps: ScheduleChangeApprovalStep[];
  current_step?: number;
  created_at: string;
}

// ── Analytics ────────────────────────────────────────────────────

export interface AnalyticsCategoryInfo {
  code: string;
  name: string;
  compensation_type?: string;
}

export interface OvertimeMonthBreakdown {
  month: number;
  month_label: string;
  total_minutes: number;
  total_hours: number;
  by_category: Record<string, number>;
  log_count: number;
  /** Null when the caller is not a salary viewer (see pay_hidden). */
  total_pay: number | null;
  total_credits: number;
}

export interface OvertimeTrendsResponse {
  year: number;
  categories: AnalyticsCategoryInfo[];
  months: OvertimeMonthBreakdown[];
  pay_hidden?: boolean;
}

export interface PaidUnpaidMonth {
  month: number;
  month_label: string;
  paid_minutes: number;
  paid_hours: number;
  unpaid_minutes: number;
  unpaid_hours: number;
  total_minutes: number;
  total_hours: number;
}

export interface OvertimePaidUnpaidResponse {
  year: number;
  months: PaidUnpaidMonth[];
}

export interface AnalyticsLeaveTypeInfo {
  code: string;
  name: string;
}

export interface LeaveMonthBreakdown {
  month: number;
  month_label: string;
  total_days: number;
  application_count: number;
  by_type: Record<string, number>;
}

export interface LeaveTrendsResponse {
  year: number;
  leave_types: AnalyticsLeaveTypeInfo[];
  months: LeaveMonthBreakdown[];
}

export interface AttendanceMonthSummary {
  month: number;
  month_label: string;
  total_records: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  avg_hours_worked: number;
  total_tardiness_minutes: number;
  total_undertime_minutes: number;
  total_overtime_minutes: number;
}

export interface AttendanceSummaryResponse {
  year: number;
  months: AttendanceMonthSummary[];
}

export interface AnalyticsOverviewResponse {
  total: number;
  active: number;
  inactive: number;
}

// ── Compensation & payout scheduling ──────────────────────────────
export interface CutoffRule {
  cutoff_start_day: number;
  cutoff_end_day: number;
  payout_day: number;
  payout_month_offset: number;
}

export interface PayoutSchedule {
  id: number;
  name: string;
  frequency: 'semi_monthly' | 'monthly' | 'weekly' | 'bi_weekly';
  cutoffs: CutoffRule[];
  payout_day_adjust: 'none' | 'prev_business_day' | 'next_business_day';
  is_active: boolean;
}

export interface PayoutScheduleInput {
  name: string;
  frequency: 'semi_monthly' | 'monthly' | 'weekly' | 'bi_weekly';
  cutoffs: CutoffRule[];
  payout_day_adjust: 'none' | 'prev_business_day' | 'next_business_day';
  is_active?: boolean;
}

export type CompensationKind =
  | 'bonus' | 'incentive' | 'allowance' | 'salary_adjustment' | 'leave_cash' | 'correction';

export interface CompensationItem {
  id: number;
  employee_id: number;
  kind: CompensationKind;
  amount: number;
  earned_on: string;
  payout_date: string;
  recurrence: 'once' | 'monthly' | 'per_cutoff';
  template_id?: number | null;
  status: 'pending' | 'scheduled' | 'paid' | 'void';
  reason: string;
  meta?: Record<string, unknown> | null;
  payroll_item_id?: number | null;
  created_at?: string;
}

export interface CompensationItemInput {
  employee_id: number;
  kind: CompensationKind;
  amount: number;
  earned_on: string;
  recurrence?: 'once' | 'monthly' | 'per_cutoff';
  reason: string;
  payout_date?: string;
  meta?: Record<string, unknown>;
}

export interface CurrentSalaryRow {
  employee_id: number;
  employee_name: string;
  email?: string | null;
  employee_type?: string | null;
  salary_grade_id?: number | null;
  salary_grade_code?: string | null;
  salary_grade_name?: string | null;
  monthly_rate?: number | null;
  effective_date?: string | null;
}

export interface RaiseResultRow {
  employee_id: number;
  status: 'applied' | 'skipped';
  from_basic?: number | null;
  to_basic?: number | null;
  delta?: number | null;
  effective_date?: string | null;
  reason?: string | null;
}

// ── Employee self-service payslips ──────────────────────────────
export interface MyPayslipSummary {
  period_id: number;
  period_name: string;
  start_date: string;
  end_date: string;
  payout_date?: string | null;
  status: string;
  gross_pay: number;
  total_deductions: number;
  net_pay: number;
}

export interface MyPayslipDetail {
  period_id: number;
  period_name: string;
  start_date: string;
  end_date: string;
  payout_date?: string | null;
  status: string;
  employee_name: string;
  grade_name?: string | null;
  base_pay: number;
  overtime_pay: number;
  gross_pay: number;
  total_deductions: number;
  total_contributions: number;
  net_pay: number;
  breakdown: Record<string, unknown>;
}

// ── Salary access enrollment + approval ──────────────────────────────

export type SalaryEnrollmentKind = 'viewer' | 'approver';
export type SalaryRequestStatus = 'pending' | 'approved' | 'declined' | 'cancelled';

export interface SalaryEnrollmentRow {
  id: number;
  user_id: number;
  user_name: string;
  kind: SalaryEnrollmentKind;
  status: string;
  granted_by?: number | null;
  /** Null when granted at setup rather than by a person. */
  granted_by_name?: string | null;
  granted_at?: string | null;
}

export interface SalaryRequestRow {
  id: number;
  user_id: number;
  user_name: string;
  kind: SalaryEnrollmentKind;
  status: SalaryRequestStatus;
  reason?: string | null;
  requested_at?: string | null;
  decided_by?: number | null;
  decided_at?: string | null;
  decision_note?: string | null;
  /** Why the signed-in approver may not approve this one; null if they may. */
  approval_block?: string | null;
}

/** One line of the salary access history (who granted what to whom, when). */
export interface SalaryGrantHistoryRow {
  id: number;
  at?: string | null;
  action: string;
  label: string;
  actor_id?: number | null;
  actor_name?: string | null;
  subject_id?: number | null;
  subject_name?: string | null;
  kind?: SalaryEnrollmentKind | null;
}

export interface MySalaryStatus {
  is_viewer: boolean;
  is_approver: boolean;
  pending_kinds: string[];
}

export interface SalaryRequestByToken {
  id: number;
  user_id: number;
  user_name: string;
  kind: SalaryEnrollmentKind;
  reason?: string | null;
  requested_at?: string | null;
}

// ── Notifications ────────────────────────────────────────────────────

export interface NotificationRow {
  id: number;
  type: string;
  title: string;
  body?: string | null;
  action_type?: string | null;
  action_ref_id?: number | null;
  is_read: boolean;
  is_actioned: boolean;
  created_at?: string | null;
}

export interface NotificationList {
  items: NotificationRow[];
  unread_count: number;
}

export interface ScheduleLintViolation {
  employee_id: number;
  date: string;
  type: 'max_consecutive_work_days' | 'min_rest_days_per_week' | 'approved_leave' | 'holiday';
  message: string;
}

// ── Time clock ───────────────────────────────────────────────────────────────

export interface TimePunch {
  id: number;
  employee_id: number;
  business_date: string;
  punch_type: 'in' | 'out';
  shift_id?: number | null;
  work_arrangement?: string | null;
  punched_at: string;
  local_time: string;
  clock_skew_seconds?: number | null;
  latitude?: number | null;
  longitude?: number | null;
  accuracy_m?: number | null;
  /** captured | recaptured | denied | unavailable | timeout | insecure_context | not_required */
  location_status: string;
  recapture_deadline?: string | null;
  /** inside | outside | not_applicable | unverified */
  geofence_status: string;
  work_site_id?: number | null;
  distance_m?: number | null;
  notes?: string | null;
}

export interface TimeclockShiftInfo {
  shift_id: number;
  sequence_number: number;
  start_time?: string | null;
  end_time?: string | null;
  status: string;
  work_arrangement?: string | null;
  /** require_site | any_location | record_only */
  geofence_mode: string;
  work_site_id?: number | null;
}

export interface TimeclockToday {
  timeclock_enabled: boolean;
  require_location: boolean;
  grace_minutes: number;
  business_date: string;
  server_time: string;
  next_action: 'clock_in' | 'clock_out';
  open_punch?: TimePunch | null;
  punches: TimePunch[];
  shifts: TimeclockShiftInfo[];
  hours_today?: number | null;
}

export interface WorkSite {
  id: number;
  name: string;
  code?: string | null;
  latitude: number;
  longitude: number;
  radius_m: number;
  address?: string | null;
  org_node_id?: number | null;
  is_active: boolean;
}

export interface WorkArrangementRule {
  id: number;
  code: string;
  label: string;
  geofence_mode: 'require_site' | 'any_location' | 'record_only';
  is_active: boolean;
  sort_order: number;
}

// ── Area E (employees, profile, audit) ───────────────────────────────
// Added as interface merges so the shared declarations above stay untouched.

export type CustomFieldValue = string | number | boolean | null;
export type CustomFieldType = 'text' | 'number' | 'date' | 'select' | 'boolean';
export type CustomFieldVisibility = 'hr_only' | 'managers' | 'employee_view' | 'employee_edit';

export interface User {
  middle_name?: string | null;
  org_node_id?: number | null;
  org_node_name?: string | null;
  reports_to_name?: string | null;
  invite_pending?: boolean;
  invite_expired?: boolean;
  custom_fields?: Record<string, CustomFieldValue>;
}

export interface AppSettings {
  employee_number_label?: string | null;
}

export interface CustomFieldDefinition {
  id: number;
  key: string;
  label: string;
  field_type: CustomFieldType;
  options: string[];
  is_required: boolean;
  is_unique: boolean;
  regex: string | null;
  visibility: CustomFieldVisibility;
  is_sensitive: boolean;
  help_text: string | null;
  sort_order: number;
  is_archived: boolean;
}

export interface CustomFieldConfig {
  employee_number_label: string;
  default_employee_number_label: string;
  can_manage: boolean;
  fields: CustomFieldDefinition[];
}

export interface EmployeeImportRow {
  row: number;
  email: string | null;
  name: string;
  action: 'create' | 'update' | 'unchanged' | 'error';
  errors: string[];
  changes: string[];
  user_id?: number;
  invited?: boolean;
}

export interface EmployeeImportResult {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  unchanged: number;
  failed: number;
  ignored_columns: string[];
  columns: string[];
  rows: EmployeeImportRow[];
}

export type EmployeeBulkAction =
  | 'set_employee_type'
  | 'set_schedule_format'
  | 'set_org_unit'
  | 'set_reports_to'
  | 'send_invite'
  | 'separate';

export interface EmployeeBulkRequest {
  action: EmployeeBulkAction;
  user_ids?: number[];
  filter?: {
    search?: string;
    role?: string;
    is_active?: boolean;
    separation_type?: string;
    org_node_id?: number;
    custom?: Record<string, string>;
  };
  value?: string | number | null;
  separation?: {
    separation_type: 'resigned' | 'terminated';
    separation_date: string;
    separation_reason?: string;
    delete_future_shifts: boolean;
  };
}

export interface EmployeeBulkResponse {
  action: EmployeeBulkAction;
  total: number;
  updated: number;
  skipped: number;
  failed: number;
  results: { user_id: number; name: string; status: 'updated' | 'skipped' | 'error'; message?: string | null }[];
}

export interface AuditLogEntry {
  user_name?: string | null;
  action_label?: string;
  description?: string;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface TwoFactorStatus {
  enabled: boolean;
  pending_setup: boolean;
  recovery_codes_remaining: number;
}

export interface TwoFactorSetup {
  secret: string;
  qr_code_uri: string;
  qr_code_base64: string;
  backup_codes: string[];
}

export interface ActiveSession {
  id: number;
  ip_address: string | null;
  user_agent: string | null;
  login_at: string | null;
  last_activity_at: string | null;
  is_current: boolean;
}

export interface LoginEvent {
  id: number;
  user_email: string | null;
  action: 'login_success' | 'login_failure';
  ip_address: string | null;
  user_agent: string | null;
  created_at: string | null;
}

// ── Area L: leave approvals, day counting and organization (2026-09) ──
// Declaration merging adds fields to the interfaces above without editing them.

export type LeaveHalfDay = 'am' | 'pm';

/** What the CALLER may do with a request, as the API will judge it. */
export interface LeaveActions {
  can_edit: boolean;
  can_cancel: boolean;
  can_review: boolean;
  can_self_approve: boolean;
  can_override: boolean;
  can_reassign: boolean;
  can_revoke: boolean;
}

export interface LeaveDayBreakdownItem {
  date: string;
  days: number;
  reason: string;
  label: string;
}

export interface LeaveRuleViolation {
  rule: string;
  mode: 'block' | 'warn';
  message: string;
  details?: Record<string, unknown>;
}

export interface LeaveApprovalEvent {
  id: number;
  action: string;
  actor_id?: number | null;
  actor_name?: string | null;
  from_approver_id?: number | null;
  from_approver_name?: string | null;
  to_approver_id?: number | null;
  to_approver_name?: string | null;
  reason?: string | null;
  created_at?: string | null;
}

export interface LeaveApplication {
  leave_type_name?: string | null;
  half_day?: LeaveHalfDay | null;
  day_breakdown?: LeaveDayBreakdownItem[] | null;
  rule_warnings?: LeaveRuleViolation[] | null;
  events?: LeaveApprovalEvent[];
  actions?: LeaveActions;
}

export interface LeaveApprovalStep {
  /** The requester's own step: only when nobody else can approve leave. */
  is_self?: boolean;
}

export interface LeavePrecheckResult {
  allowed: boolean;
  days_requested: number;
  violations: LeaveRuleViolation[];
  warnings: LeaveRuleViolation[];
  day_breakdown: LeaveDayBreakdownItem[];
  days_by_year: Record<string, number>;
  problem: string | null;
}

export interface ApproverRuleStep {
  step_order?: number;
  approver_id?: number | null;
  approver_name?: string | null;
  approver_role?: ApproverRole | null;
  approver_active?: boolean;
}

export interface LeaveApproverAssignment {
  steps?: ApproverRuleStep[];
  deactivated_reason?: string | null;
  granted_role_to?: string[];
}

export interface ApproverCheck {
  user_id: number;
  name?: string | null;
  found: boolean;
  is_active: boolean;
  has_reviewer_role: boolean;
  will_grant_role: boolean;
  message: string;
}

export interface ApprovalChainPreviewItem {
  is_deputy?: boolean;
  node_name?: string | null;
}

/** One step of GET /organizations/approval-chain (same resolver as filing). */
export interface EffectiveChainStep {
  step_order: number;
  approver_id: number;
  approver_name: string;
  source: string;
  is_deputy: boolean;
  node_name?: string | null;
}

export interface EffectiveChainResponse {
  employee_id: number;
  employee_name: string;
  chain: EffectiveChainStep[];
}

export interface OrgLevelItem {
  /** Existing level being kept; omit for a new level. */
  id?: number;
}

export interface OrgNodeDeletePreview {
  node_id: number;
  node_name: string;
  parent_id: number | null;
  parent_name: string | null;
  can_delete: boolean;
  blocked_reason: string | null;
  members_moved: Array<{ id: number; name: string }>;
  secondary_members: Array<{ id: number; name: string }>;
  children_moved: Array<{ id: number; name: string }>;
  approver_rules_deactivated: Array<{ id: number; description: string }>;
  policy_rules_changed: Array<{ id: number; name: string; deactivated: boolean }>;
}

export interface AppSettings {
  work_week_days?: number[];
  leave_reminder_after_days?: number;
  leave_escalate_after_days?: number;
}

// ── Area S: schedule grid, holidays (2026-09 audit) ─────────────────────────
// Added as interface merges so the declarations above stay untouched.

export interface ScheduleEmployee {
  /** Whether the viewer may change this row. Visibility is wider than management. */
  can_manage?: boolean;
}

export interface Shift {
  /** Set when the shift is an approved leave day; such shifts cannot be moved or swapped. */
  leave_application_id?: number | null;
  /** Where the employee is expected to work (used by the time clock geofence). */
  work_site_id?: number | null;
}

export interface ShiftBulkDeleteResult {
  deleted_count: number;
  leave_kept_count: number;
  employee_count: number;
  dry_run: boolean;
}

export interface PublishRangeResult {
  published_count: number;
  notified: number;
  employee_count: number;
  dry_run: boolean;
}

export interface UnpublishRangeResult {
  unpublished_count: number;
  notified: number;
  employee_count: number;
  dry_run: boolean;
}

export interface AppSettings {
  // Area S: working-hour rules. 0 / false = off.
  max_work_hours_per_day?: number;
  max_work_hours_per_week?: number;
  min_rest_hours_between_shifts?: number;
  check_overlapping_shifts?: boolean;
}

export interface DateRemark {
  /** For a recurring holiday listed in another year: the row's own date (edit this). */
  stored_date?: string;
  source?: 'manual' | 'feed';
  is_tentative?: boolean;
  /** ISO 3166-2 subdivision code of a regional holiday, e.g. PH-CEB. */
  region?: string | null;
  needs_review?: boolean;
  locally_modified?: boolean;
}

export interface HolidayRegion {
  code: string;
  label: string;
  count: number;
  samples: string[];
}

export interface HolidaySourceConfig {
  provider: 'officeholidays' | 'ics_url';
  country_slug: string | null;
  feed_url: string | null;
  include_regions: string[];
  auto_sync: boolean;
  last_synced_at: string | null;
  last_status: 'ok' | 'error' | null;
  last_error: string | null;
  last_counts: Record<string, number> | null;
  discovered_regions: HolidayRegion[] | null;
  configured: boolean;
  /** The tenant's own country as a feed slug, used as the picker default. */
  suggested_country_slug: string | null;
  countries: { slug: string; name: string }[];
}

export interface HolidaySyncItem {
  date: string;
  title: string;
  is_special: boolean;
  is_tentative: boolean;
  needs_review: boolean;
  region: string | null;
  reason?: string;
  before?: { title: string; is_special: boolean; is_tentative: boolean } | null;
}

export interface HolidaySyncResult {
  dry_run: boolean;
  added: HolidaySyncItem[];
  changed: HolidaySyncItem[];
  removed: HolidaySyncItem[];
  skipped: HolidaySyncItem[];
  needs_review: HolidaySyncItem[];
  regions: HolidayRegion[];
  holiday_off_created: number;
}

// ── Area P: role-appropriate home dashboard (GET /analytics/dashboard) ──
export interface PersonalDashboardShift {
  date: string;
  start_time: string | null;
  end_time: string | null;
  status: string;
  status_label: string;
  category: string | null;
}

export interface PersonalDashboard {
  today: string;
  next_shifts: PersonalDashboardShift[];
  // null when the balance could not be computed (not "0 days left").
  leave_balances: { leave_type: string; name: string; available_days: number; total_days: number }[] | null;
  pending_leave_requests: { id: number; leave_type: string; start_date: string; end_date: string; days: number }[];
  pending_schedule_requests: number;
  clock: { enabled: boolean; clocked_in: boolean; since: string | null };
}

export interface HomeDashboard {
  // company: metrics cover everyone; team: only the employees you manage;
  // personal: no reports:view, so metrics is null.
  view: 'company' | 'team' | 'personal';
  metrics: DashboardMetrics | null;
  personal: PersonalDashboard;
}

// ── Area R: report layouts, data options, templates, scheduled-export runs ──
// These extend the report-builder interfaces declared above (TypeScript merges
// same-named interfaces), so this block stays append-only.

export interface HeadingRow {
  text: string;
  /** How many columns the line spans from the left; unset = all of them. */
  span?: number | null;
  align?: 'left' | 'center' | 'right';
  bold?: boolean;
}

/** A heading over the columns `from`..`to` (instance ids, e.g. "date::2"). */
export interface HeaderBand {
  label: string;
  from: string;
  to: string;
}

export interface BlockSpec {
  by: string;
  blank_rows_between: number;
  repeat_value: 'every_row' | 'first_row';
  sheet_per_group: boolean;
}

export interface LayoutSpec {
  heading_rows: HeadingRow[];
  header_tiers: HeaderBand[][];
  blocks?: BlockSpec | null;
  sheet_name?: string | null;
  style: 'plain' | 'banded';
  freeze_header: boolean;
}

export interface DataSourceOption {
  key: string;
  label: string;
  type: 'boolean' | 'string' | 'choice';
  default?: unknown;
  help?: string | null;
  choices?: { value: string; label: string }[];
}

export interface DataSource {
  options?: DataSourceOption[];
}

export interface DataSourceColumn {
  is_custom?: boolean;
}

export interface ExportSpec {
  layout?: LayoutSpec | null;
  source_options?: Record<string, unknown>;
  /** Fills {report_name} and names the downloaded workbook's sheet. */
  report_name?: string;
}

export interface DataExportConfig {
  layout?: LayoutSpec | null;
  source_options?: Record<string, unknown>;
}

export interface PreviewColumn {
  type?: string | null;
}

export interface PreviewResponse {
  /** The layout's headings with {tokens} filled in. */
  headings?: string[];
  /** The worksheet names the download will have. */
  sheet_names?: string[];
}

export interface ScheduledExport {
  /** The next run in the company's own time, e.g. "Mon 29 Sep 2026, 08:00". */
  next_run_local?: string | null;
  timezone?: string | null;
  owner_name?: string | null;
}

export interface ScheduledExportRun {
  id: number;
  status: string;
  error?: string | null;
  ran_at?: string | null;
  rows?: number | null;
  delivered?: number | null;
  recipients?: number | null;
}

export interface ReportTemplate {
  key: string;
  name: string;
  description: string;
  spec: ExportSpec;
}

// ── Area F: payroll, finance, attendance, time clock (2026-09 audit) ──────────
// Interface merges, so the declarations above stay untouched.

export interface DeductionType {
  calculation_basis?: 'gross' | 'base';
}

/** One band of a tiered deduction table. For a basis B in [over_amount, up_to_amount):
 *  amount = base_amount + rate x (B if rate_basis is 'full', else B - over_amount). */
export interface DeductionBracket {
  id?: number;
  over_amount: number;
  up_to_amount: number | null;
  base_amount: number;
  rate: number;
  rate_basis: 'excess' | 'full';
}

export interface PayrollComputeWarning {
  employee_id: number;
  employee_name: string;
  message: string;
}

export interface PayrollSkippedEmployee {
  employee_id: number;
  employee_name: string;
  reason: string;
}

/** While computing: {done, total}. Afterwards: who was skipped, any warnings,
 *  or (compute_failed) the error. */
export interface PayrollComputeProgress {
  done?: number;
  total?: number;
  skipped?: PayrollSkippedEmployee[];
  warnings?: PayrollComputeWarning[];
  error?: string;
}

export interface PayrollPeriod {
  payout_date?: string | null;
  schedule_id?: number | null;
  compute_progress?: PayrollComputeProgress | null;
}

export interface PayslipLine {
  name: string;
  amount: number;
  code?: string | null;
  kind?: string;
}

export interface MyPayslipDetail {
  /** Taken from the employee's pay; adds up to total_deductions. */
  employee_deductions: PayslipLine[];
  /** Paid by the employer on top; not deducted from the employee. */
  employer_contributions: PayslipLine[];
}

export interface AttendanceRecord {
  status_override?: string | null;
  self_reported?: boolean;
  is_rest_day_work?: boolean;
  auto_marked?: boolean;
  excused_by_leave_id?: number | null;
}

export interface OvertimeLog {
  log_type?: string;
  payroll_period_id?: number | null;
  paid_at?: string | null;
  default_leave_type?: string | null;
}

export interface TardinessRecord {
  amount_hidden?: boolean;
}

export interface SuggestedDeduction {
  minutes: number;
  amount: number | null;
  amount_hidden: boolean;
  has_salary: boolean;
}

export interface ConversionLeaveType {
  code: string;
  name: string;
}

export interface TimePunch {
  source?: string | null;
  auto_closed?: boolean;
  employee_name?: string | null;
  work_site_name?: string | null;
}

export interface MySalaryStatus {
  pending_requests?: { id: number; kind: string }[];
}

export interface AppSettings {
  // Area F: attendance automation.
  auto_clockout_after_hours?: number;
  auto_clockout_unscheduled_hours?: number;
  auto_mark_absent?: boolean;
  auto_absent_after_minutes?: number;
}

// ── Area A: setup checklist, background jobs, data retention ─────────
export interface AppSettings {
  // Housekeeping windows, in days (the daily cleanup job).
  audit_log_retention_days?: number;
  login_history_retention_days?: number;
  read_notification_retention_days?: number;
}

export interface SetupStep {
  key: string;
  label: string;
  done: boolean;
  count: number;
  link: string;
  /** Who does it: 'finance' steps are done from the finance dashboard, so
   * the admin dashboard lists them without a link. */
  by?: 'admin' | 'finance';
}

export interface SetupStatus {
  steps: SetupStep[];
  completed: number;
  total: number;
}

export interface JobRunRow {
  id: number;
  job_name: string;
  period_key: string;
  status: 'running' | 'success' | 'failed';
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  meta: Record<string, unknown> | null;
}

export interface OutboxItem {
  id: number;
  to_email: string;
  subject: string;
  type: string | null;
  status: 'queued' | 'failed' | 'skipped';
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string | null;
}

export interface BackgroundJobsView {
  tick_seconds: number;
  stale_after_minutes: number;
  max_email_attempts: number;
  jobs: { name: string; cadence: 'tick' | 'hourly' | 'daily' }[];
  runs: JobRunRow[];
  outbox: {
    counts: Record<'queued' | 'sent' | 'failed' | 'skipped', number>;
    items: OutboxItem[];
  };
}

export interface RetentionReport {
  retention_days: number | null;
  cutoff_date: string | null;
  employees: { id: number; name: string; separation_date: string | null }[];
  counts: { type: string; label: string; count: number }[];
  total: number;
}

// Admin mode: what the signed-in session is. Present on the user returned by
// /auth/me and the sign-in responses; absent on other users.
export type Portal = 'employee' | 'admin' | 'finance';

export interface User {
  portal?: Portal;
  admin_eligible?: boolean;
  /** Holds the finance role (dormant or not): may use the finance sign-in. */
  finance_eligible?: boolean;
  has_employee_workspace?: boolean;
  expires_at?: string | null;
  admin_expires_at?: string | null;
  idle_timeout_seconds?: number | null;
}

// Finances: pay rules, the company-wide rates payroll applies (GET/PUT /payroll/pay-rules).
export interface PayRules {
  working_days_per_month: number;
  night_diff_multiplier: number;
  /** "HH:MM:SS"; null on either end means no night window, so no night differential. */
  night_shift_start: string | null;
  night_shift_end: string | null;
  holiday_worked_multiplier: number;
  special_holiday_worked_multiplier: number;
}

// Administration is not operations (2026-09-29): the admin dashboard's
// questions, from GET /settings/admin-overview (admin session only).
export interface AdminOverviewJob {
  key: 'schedules' | 'leave' | 'reports' | 'finance';
  label: string;
  /** Role codes that do this job. */
  roles: string[];
  /** Active people holding any of them. */
  holders: number;
}

export interface AdminOverview {
  users_without_roles: { id: number; name: string; email: string }[];
  jobs: AdminOverviewJob[];
  nobody_can_approve_leave: boolean;
  leave_without_approver: { id: number; employee_name: string; start_date: string; end_date: string }[];
  /** Null when this administrator is not a salary-access approver. */
  salary_requests_pending: number | null;
}

// Who would approve a leave request. Empty with nobody_can_approve when
// nobody in the company can approve leave; `message` says what to do.
export interface ApprovalChainPreviewResult {
  chain: ApprovalChainPreviewItem[];
  nobody_can_approve?: boolean;
  message?: string | null;
}
