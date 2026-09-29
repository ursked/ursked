import { User } from '@/types';

// Admin mode. Every sign-in session is either an EMPLOYEE session (the
// ordinary sign-in page, for everyone) or an ADMIN session (the administrator
// sign-in page, tenant administrators only). The server records which on the
// session and enforces it on every request; in an employee session an
// administrator's tenant_admin role is dormant and /auth/me leaves it out of
// `roles`, so every hasRole/hasPermission check in the app already answers as
// the server will. These helpers only decide which workspace to draw.

export const ADMIN_LOGIN_PATH = '/admin/login';
export const EMPLOYEE_LOGIN_PATH = '/auth/login';

export type Workspace = 'employee' | 'admin';

export function workspaceOf(user: User | null | undefined): Workspace {
  return user?.portal === 'admin' ? 'admin' : 'employee';
}

export function isAdminSession(user: User | null | undefined): boolean {
  return workspaceOf(user) === 'admin';
}

/** Holds the administrator role at all, so may use the administrator sign-in. */
export function isAdminEligible(user: User | null | undefined): boolean {
  return !!user?.admin_eligible;
}

/** False for a pure administrator account: no schedule, leave or payslips of
 * its own, so its employee workspace is only a pointer to the admin sign-in. */
export function hasEmployeeWorkspace(user: User | null | undefined): boolean {
  return user?.has_employee_workspace !== false;
}

/** Where to send someone whose session ended, by the door they came through. */
export function signInPathFor(workspace: Workspace): string {
  return workspace === 'admin' ? ADMIN_LOGIN_PATH : EMPLOYEE_LOGIN_PATH;
}
