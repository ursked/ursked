import { User } from '@/types';

// Sign-in doors. Every session is one of three kinds, recorded by the server
// on the session and enforced on every request:
//   * EMPLOYEE, from the ordinary sign-in page, for everyone. The day-to-day
//     work of the company is done here: schedules, leave approvals,
//     attendance, reports, each by the people holding the role for it. The
//     administrator and finance roles are dormant.
//   * ADMIN, from the administrator sign-in page, for tenant administrators.
//     Running the system (accounts, roles, org chart, settings, policies) and
//     nothing operational: "a manager for graphics is not an administrator of
//     the app", nor is an administrator a manager for being one.
//   * FINANCE, from the finance sign-in page, for the finance role. Payroll
//     and the rest of Finances, on a dashboard of its own.
// /auth/me lists only the roles in force for the session, and
// /permissions/me answers for the session, so every hasRole/hasPermission
// check in the app already answers as the server will. These helpers only
// decide which workspace to draw and which door to send someone back to.

export const ADMIN_LOGIN_PATH = '/admin/login';
export const FINANCE_LOGIN_PATH = '/finance/login';
export const EMPLOYEE_LOGIN_PATH = '/auth/login';

export type Workspace = 'employee' | 'admin' | 'finance';

export function workspaceOf(user: User | null | undefined): Workspace {
  if (user?.portal === 'admin') return 'admin';
  if (user?.portal === 'finance') return 'finance';
  return 'employee';
}

export function isAdminSession(user: User | null | undefined): boolean {
  return workspaceOf(user) === 'admin';
}

export function isFinanceSession(user: User | null | undefined): boolean {
  return workspaceOf(user) === 'finance';
}

/** An admin or finance session: ends on its own when idle, has its own bar. */
export function isPrivilegedSession(user: User | null | undefined): boolean {
  return workspaceOf(user) !== 'employee';
}

/** Holds the administrator role at all, so may use the administrator sign-in. */
export function isAdminEligible(user: User | null | undefined): boolean {
  return !!user?.admin_eligible;
}

/** Holds the finance role at all, so may use the finance sign-in. */
export function isFinanceEligible(user: User | null | undefined): boolean {
  return !!user?.finance_eligible;
}

/** Has a second dashboard to tell the employee one apart from. */
export function hasOtherDashboard(user: User | null | undefined): boolean {
  return isAdminEligible(user) || isFinanceEligible(user);
}

/** False for a pure administrator account: no schedule, leave or payslips of
 * its own, so its employee workspace is only a pointer to the admin sign-in. */
export function hasEmployeeWorkspace(user: User | null | undefined): boolean {
  return user?.has_employee_workspace !== false;
}

/** Where to send someone whose session ended, by the door they came through. */
export function signInPathFor(workspace: Workspace): string {
  if (workspace === 'admin') return ADMIN_LOGIN_PATH;
  if (workspace === 'finance') return FINANCE_LOGIN_PATH;
  return EMPLOYEE_LOGIN_PATH;
}
